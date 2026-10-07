"""
Benchmark Evaluation Harness & Metrics Collector for Legal RAG (OPT-018).

Executes benchmark test cases against isolated RAG components or API client,
collecting evaluations for:
1. Answer correctness (Pass/Fail/Not_Evaluable)
2. Retrieval correctness (Pass/Fail/Not_Evaluable)
3. Citation correctness (Pass/Fail/Not_Evaluable)
4. Refusal correctness (Pass/Fail/Not_Evaluable)
5. Grounding correctness (Pass/Fail/Not_Evaluable)
6. LLM invocation behavior (actual vs expected)
7. Token usage (actual vs estimated vs unknown)
8. Estimated cost (USD, actual vs estimated vs null)
9. Latencies (monotonic timer ms: retrieval, embedding, llm, total)
"""

import time
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

from tests.evaluation.benchmark_dataset import BenchmarkCase, BenchmarkCategory


class EvaluationStatus(str):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_EVALUABLE = "NOT_EVALUABLE"


class CaseEvaluationResult(BaseModel):
    case_id: str
    category: str
    question: str
    status: str = "PASS"  # Overall status: PASS if all applicable metrics PASS, FAIL if any FAILS

    # Specific metric outcomes
    answer_eval: str = "PASS"
    retrieval_eval: str = "PASS"
    citation_eval: str = "PASS"
    refusal_eval: str = "PASS"
    grounding_eval: str = "PASS"
    llm_invocation_eval: str = "PASS"

    # Explanations / details
    notes: List[str] = Field(default_factory=list)

    # Actual measurements captured from response/telemetry
    actual_answer: str = ""
    actual_confidence: str = ""
    actual_retrieved_count: int = 0
    actual_citation_count: int = 0
    llm_invoked: bool = False

    # Telemetry data
    token_usage_type: str = "unknown"
    actual_tokens: Optional[int] = None
    estimated_tokens: Optional[int] = None
    estimated_cost_usd: Optional[float] = None

    # Measured latencies (milliseconds)
    total_latency_ms: float = 0.0
    retrieval_latency_ms: Optional[float] = None
    embedding_latency_ms: Optional[float] = None
    llm_latency_ms: Optional[float] = None


class BenchmarkSummary(BaseModel):
    total_cases: int = 0
    passed_cases: int = 0
    failed_cases: int = 0
    not_evaluable_cases: int = 0

    category_accuracy: Dict[str, Dict[str, int]] = Field(default_factory=dict)

    # Metric-specific pass rates
    answer_pass_count: int = 0
    retrieval_pass_count: int = 0
    citation_pass_count: int = 0
    refusal_pass_count: int = 0
    grounding_pass_count: int = 0

    # Token & Cost rollup
    total_estimated_tokens: int = 0
    total_actual_tokens: int = 0
    total_estimated_cost_usd: float = 0.0

    # Latency rollup (average in ms)
    avg_total_latency_ms: float = 0.0
    avg_retrieval_latency_ms: float = 0.0
    avg_embedding_latency_ms: float = 0.0
    avg_llm_latency_ms: float = 0.0

    case_results: List[CaseEvaluationResult] = Field(default_factory=list)


def evaluate_case(case: BenchmarkCase, response_data: Dict[str, Any]) -> CaseEvaluationResult:
    """
    Deterministically evaluates a single benchmark case against actual API / service response data.
    """
    notes: List[str] = []
    answer = response_data.get("answer", "")
    sources = response_data.get("sources", [])
    confidence = response_data.get("confidence", "supported")
    telemetry = response_data.get("telemetry") or {}

    retrieved_count = telemetry.get("retrieved_chunks_count", len(sources))
    llm_latency = telemetry.get("llm_latency_ms")
    # An LLM invocation occurred if llm_latency was recorded > 0.0 or llm_provider != none/deterministic
    llm_provider = telemetry.get("llm_provider") or ""
    llm_invoked = bool((llm_latency is not None and llm_latency > 0.0) or (
        llm_provider and "deterministic" not in llm_provider and llm_provider != "none"
    ))

    token_usage_type = telemetry.get("token_usage_type", "unknown")
    actual_tokens = telemetry.get("total_tokens")
    estimated_tokens = telemetry.get("estimated_total_tokens")
    estimated_cost = telemetry.get("estimated_total_cost")

    total_latency_ms = telemetry.get("total_latency_ms", 0.0)
    retrieval_latency_ms = telemetry.get("retrieval_latency_ms")
    embedding_latency_ms = telemetry.get("embedding_latency_ms")

    # 1. Answer Evaluation
    answer_eval = EvaluationStatus.PASS
    if case.expected_refusal:
        # Expected refusal: answer should communicate insufficient info
        refusal_phrase_present = any(phrase.lower() in answer.lower() for phrase in case.expected_answer_contains)
        if not refusal_phrase_present:
            answer_eval = EvaluationStatus.FAIL
            notes.append(f"Answer failed: expected refusal phrase not found in '{answer}'")
        # Forbidden phrases check
        for forbidden in case.forbidden_answer_contains:
            if forbidden.lower() in answer.lower():
                answer_eval = EvaluationStatus.FAIL
                notes.append(f"Answer failed: forbidden phrase '{forbidden}' present in refusal answer")
    else:
        # Expected supported answer: must contain expected facts
        for expected in case.expected_answer_contains:
            if expected.lower() not in answer.lower():
                answer_eval = EvaluationStatus.FAIL
                notes.append(f"Answer failed: expected factual phrase '{expected}' not found in '{answer}'")

    # 2. Refusal Evaluation
    refusal_eval = EvaluationStatus.PASS
    if case.expected_refusal:
        if confidence != "insufficient_context":
            refusal_eval = EvaluationStatus.FAIL
            notes.append(f"Refusal failed: confidence was '{confidence}', expected 'insufficient_context'")
        if len(sources) > 0:
            refusal_eval = EvaluationStatus.FAIL
            notes.append(f"Refusal failed: returned {len(sources)} sources, refusal contract requires 0 citations")
    else:
        if confidence == "insufficient_context":
            refusal_eval = EvaluationStatus.FAIL
            notes.append("Refusal failed: legitimate query was improperly refused as insufficient_context")

    # 3. Grounding Evaluation
    grounding_eval = EvaluationStatus.PASS
    if not case.expected_refusal:
        # Verify that an answer is accompanied by supporting sources when retrieval/citations are expected
        if (case.expected_retrieval_min_chunks > 0 or case.expected_citation_count_min > 0) and len(sources) == 0:
            grounding_eval = EvaluationStatus.FAIL
            notes.append("Grounding failed: supported answer provided with zero supporting sources")
    else:
        # Unanswerable cases should have no unsupported answers
        if len(sources) != 0:
            grounding_eval = EvaluationStatus.FAIL
            notes.append("Grounding failed: sources returned for ungrounded question")

    # 4. Retrieval Evaluation
    retrieval_eval = EvaluationStatus.PASS
    if case.expected_refusal:
        # For out-of-scope/unanswerable, retrieval chunks should ideally be 0 (below threshold)
        if retrieved_count > 0:
            # Note: If chunks were retrieved above threshold for unanswerable question, record note
            notes.append(f"Retrieval note: {retrieved_count} chunks retrieved above threshold for unanswerable query")
    else:
        if retrieved_count < case.expected_retrieval_min_chunks:
            retrieval_eval = EvaluationStatus.FAIL
            notes.append(f"Retrieval failed: retrieved {retrieved_count} chunks, expected at least {case.expected_retrieval_min_chunks}")

        # Check expected pages in sources/retrieval
        if case.expected_retrieval_pages:
            retrieved_pages = [s.get("page_number") for s in sources if s.get("page_number") is not None]
            for exp_page in case.expected_retrieval_pages:
                if exp_page not in retrieved_pages:
                    retrieval_eval = EvaluationStatus.FAIL
                    notes.append(f"Retrieval failed: expected page {exp_page} not found in retrieved sources {retrieved_pages}")

        # Check expected sections in sources
        if case.expected_retrieval_sections_contain:
            retrieved_sections = [s.get("section", "") for s in sources]
            for exp_sec in case.expected_retrieval_sections_contain:
                if not any(exp_sec.lower() in sec.lower() for sec in retrieved_sections):
                    retrieval_eval = EvaluationStatus.FAIL
                    notes.append(f"Retrieval failed: expected section containing '{exp_sec}' not found in {retrieved_sections}")

    # 5. Citation Evaluation
    citation_eval = EvaluationStatus.PASS
    if case.expected_refusal:
        if len(sources) > 0:
            citation_eval = EvaluationStatus.FAIL
            notes.append(f"Citation failed: citations present ({len(sources)}) for refusal case")
    else:
        if len(sources) < case.expected_citation_count_min:
            citation_eval = EvaluationStatus.FAIL
            notes.append(f"Citation failed: {len(sources)} citations, expected at least {case.expected_citation_count_min}")

        for exp_cite in case.expected_citations:
            match_found = False
            for src in sources:
                page_match = exp_cite.page_number is None or src.get("page_number") == exp_cite.page_number
                sec_match = exp_cite.section_contains is None or (exp_cite.section_contains.lower() in src.get("section", "").lower())
                snip_match = exp_cite.snippet_contains is None or (exp_cite.snippet_contains.lower() in src.get("snippet", "").lower())
                doc_match = exp_cite.document_name is None or (exp_cite.document_name.lower() in src.get("document_name", "").lower())

                if page_match and sec_match and snip_match and doc_match:
                    match_found = True
                    break

            if not match_found:
                citation_eval = EvaluationStatus.FAIL
                notes.append(f"Citation failed: could not match citation spec {exp_cite.model_dump()}")

    # 6. LLM Invocation Behavior
    llm_invocation_eval = EvaluationStatus.PASS
    if case.expect_llm_invocation is not None and case.expect_llm_invocation != llm_invoked:
        llm_invocation_eval = EvaluationStatus.FAIL
        notes.append(f"LLM invocation failed: actual invocation={llm_invoked}, expected={case.expect_llm_invocation}")

    # Overall Status: FAIL if any metric failed, else PASS
    all_metrics = [answer_eval, retrieval_eval, citation_eval, refusal_eval, grounding_eval, llm_invocation_eval]
    overall_status = EvaluationStatus.FAIL if any(m == EvaluationStatus.FAIL for m in all_metrics) else EvaluationStatus.PASS

    return CaseEvaluationResult(
        case_id=case.case_id,
        category=case.category.value,
        question=case.question,
        status=overall_status,
        answer_eval=answer_eval,
        retrieval_eval=retrieval_eval,
        citation_eval=citation_eval,
        refusal_eval=refusal_eval,
        grounding_eval=grounding_eval,
        llm_invocation_eval=llm_invocation_eval,
        notes=notes,
        actual_answer=answer,
        actual_confidence=confidence,
        actual_retrieved_count=retrieved_count,
        actual_citation_count=len(sources),
        llm_invoked=llm_invoked,
        token_usage_type=token_usage_type,
        actual_tokens=actual_tokens,
        estimated_tokens=estimated_tokens,
        estimated_cost_usd=estimated_cost,
        total_latency_ms=round(total_latency_ms, 2),
        retrieval_latency_ms=round(retrieval_latency_ms, 2) if retrieval_latency_ms is not None else None,
        embedding_latency_ms=round(embedding_latency_ms, 2) if embedding_latency_ms is not None else None,
        llm_latency_ms=round(llm_latency, 2) if llm_latency is not None else None
    )


def compute_benchmark_summary(case_results: List[CaseEvaluationResult]) -> BenchmarkSummary:
    """
    Computes an aggregated benchmark report across all executed cases.
    """
    total = len(case_results)
    passed = sum(1 for r in case_results if r.status == EvaluationStatus.PASS)
    failed = sum(1 for r in case_results if r.status == EvaluationStatus.FAIL)
    not_evaluable = sum(1 for r in case_results if r.status == EvaluationStatus.NOT_EVALUABLE)

    ans_pass = sum(1 for r in case_results if r.answer_eval == EvaluationStatus.PASS)
    ret_pass = sum(1 for r in case_results if r.retrieval_eval == EvaluationStatus.PASS)
    cite_pass = sum(1 for r in case_results if r.citation_eval == EvaluationStatus.PASS)
    ref_pass = sum(1 for r in case_results if r.refusal_eval == EvaluationStatus.PASS)
    grd_pass = sum(1 for r in case_results if r.grounding_eval == EvaluationStatus.PASS)

    total_est_tokens = sum(r.estimated_tokens or 0 for r in case_results)
    total_act_tokens = sum(r.actual_tokens or 0 for r in case_results)
    total_cost = sum(r.estimated_cost_usd or 0.0 for r in case_results)

    avg_total_lat = sum(r.total_latency_ms for r in case_results) / total if total > 0 else 0.0
    ret_lats = [r.retrieval_latency_ms for r in case_results if r.retrieval_latency_ms is not None]
    avg_ret_lat = sum(ret_lats) / len(ret_lats) if ret_lats else 0.0
    emb_lats = [r.embedding_latency_ms for r in case_results if r.embedding_latency_ms is not None]
    avg_emb_lat = sum(emb_lats) / len(emb_lats) if emb_lats else 0.0
    llm_lats = [r.llm_latency_ms for r in case_results if r.llm_latency_ms is not None]
    avg_llm_lat = sum(llm_lats) / len(llm_lats) if llm_lats else 0.0

    category_stats: Dict[str, Dict[str, int]] = {}
    for r in case_results:
        if r.category not in category_stats:
            category_stats[r.category] = {"total": 0, "passed": 0, "failed": 0}
        category_stats[r.category]["total"] += 1
        if r.status == EvaluationStatus.PASS:
            category_stats[r.category]["passed"] += 1
        else:
            category_stats[r.category]["failed"] += 1

    return BenchmarkSummary(
        total_cases=total,
        passed_cases=passed,
        failed_cases=failed,
        not_evaluable_cases=not_evaluable,
        category_accuracy=category_stats,
        answer_pass_count=ans_pass,
        retrieval_pass_count=ret_pass,
        citation_pass_count=cite_pass,
        refusal_pass_count=ref_pass,
        grounding_pass_count=grd_pass,
        total_estimated_tokens=total_est_tokens,
        total_actual_tokens=total_act_tokens,
        total_estimated_cost_usd=round(total_cost, 8),
        avg_total_latency_ms=round(avg_total_lat, 2),
        avg_retrieval_latency_ms=round(avg_ret_lat, 2),
        avg_embedding_latency_ms=round(avg_emb_lat, 2),
        avg_llm_latency_ms=round(avg_llm_lat, 2),
        case_results=case_results
    )


def format_benchmark_report_text(summary: BenchmarkSummary) -> str:
    """Format human-readable summary of evaluation results."""
    lines = [
        "=" * 70,
        "LEGAL RAG EVALUATION BENCHMARK SUITE REPORT (OPT-018)",
        "=" * 70,
        f"Total Cases Evaluated: {summary.total_cases}",
        f"Passed: {summary.passed_cases} ({(summary.passed_cases / summary.total_cases * 100):.1f}%)" if summary.total_cases else "Passed: 0",
        f"Failed: {summary.failed_cases}",
        f"Not Evaluable: {summary.not_evaluable_cases}",
        "-" * 70,
        "METRIC BREAKDOWN:",
        f"  Answer Correctness:    {summary.answer_pass_count}/{summary.total_cases}",
        f"  Retrieval Correctness: {summary.retrieval_pass_count}/{summary.total_cases}",
        f"  Citation Correctness:  {summary.citation_pass_count}/{summary.total_cases}",
        f"  Refusal Correctness:   {summary.refusal_pass_count}/{summary.total_cases}",
        f"  Grounding Integrity:   {summary.grounding_pass_count}/{summary.total_cases}",
        "-" * 70,
        "CATEGORY BREAKDOWN:",
    ]
    for cat, stats in summary.category_accuracy.items():
        lines.append(f"  {cat:<18}: {stats['passed']}/{stats['total']} passed")

    lines.extend([
        "-" * 70,
        "TELEMETRY, TOKEN & COST rollup:",
        f"  Actual Tokens (Provider API):  {summary.total_actual_tokens}",
        f"  Estimated Tokens (Mock/Ratio): {summary.total_estimated_tokens}",
        f"  Estimated Cost (USD):          ${summary.total_estimated_cost_usd:.6f}",
        "-" * 70,
        "LATENCY SUMMARY (Averages):",
        f"  Avg Retrieval Latency: {summary.avg_retrieval_latency_ms:.2f} ms",
        f"  Avg Embedding Latency: {summary.avg_embedding_latency_ms:.2f} ms",
        f"  Avg LLM Latency:       {summary.avg_llm_latency_ms:.2f} ms",
        f"  Avg Total Latency:     {summary.avg_total_latency_ms:.2f} ms",
        "=" * 70
    ])

    if summary.failed_cases > 0:
        lines.append("\nFAILED CASES DETAILS:")
        for r in summary.case_results:
            if r.status != EvaluationStatus.PASS:
                lines.append(f"  Case {r.case_id} ({r.category}): {r.question}")
                for note in r.notes:
                    lines.append(f"    - {note}")
        lines.append("=" * 70)

    return "\n".join(lines)
