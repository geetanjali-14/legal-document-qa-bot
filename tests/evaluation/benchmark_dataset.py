"""
Benchmark Dataset Schema and Case Definitions for Legal RAG Evaluation Suite (OPT-018).

Provides structured evaluation test cases across required categories:
- DIRECT_FACT: Exact factual clause extraction
- MULTI_CLAUSE: Queries requiring context from multiple clauses or sections
- UNANSWERABLE: Legitimate queries whose facts are not in the document
- ADVERSARIAL: Out-of-scope / prompt injection / irrelevant queries
- CITATION: Verifying citation linkage to correct pages and sections
- RETRIEVAL: Verifying relevant chunk retrieval and ranking
"""

from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class BenchmarkCategory(str, Enum):
    DIRECT_FACT = "direct_fact"
    MULTI_CLAUSE = "multi_clause"
    UNANSWERABLE = "unanswerable"
    ADVERSARIAL = "adversarial"
    CITATION = "citation"
    RETRIEVAL = "retrieval"


class ExpectedCitation(BaseModel):
    document_name: Optional[str] = "synthetic_contract.pdf"
    page_number: Optional[int] = None
    section_contains: Optional[str] = None
    snippet_contains: Optional[str] = None


class BenchmarkCase(BaseModel):
    case_id: str
    category: BenchmarkCategory
    question: str
    description: str

    # Answer assertions
    expected_refusal: bool = False
    expected_answer_contains: List[str] = Field(default_factory=list)
    forbidden_answer_contains: List[str] = Field(default_factory=list)

    # Retrieval assertions
    expected_retrieval_min_chunks: int = 1
    expected_retrieval_pages: List[int] = Field(default_factory=list)
    expected_retrieval_sections_contain: List[str] = Field(default_factory=list)
    expected_retrieval_text_contains: List[str] = Field(default_factory=list)

    # Citation assertions
    expected_citation_count_min: int = 1
    expected_citations: List[ExpectedCitation] = Field(default_factory=list)

    # LLM execution behavior assertion: None means "dependent on retrieval threshold"
    expect_llm_invocation: Optional[bool] = True


# Canonical Benchmark Cases for synthetic_contract.pdf
BENCHMARK_CASES: List[BenchmarkCase] = [
    # -------------------------------------------------------------
    # Category A: DIRECT FACT / CLAUSE QUESTIONS
    # -------------------------------------------------------------
    BenchmarkCase(
        case_id="FACT-001",
        category=BenchmarkCategory.DIRECT_FACT,
        question="What is the termination notice period?",
        description="Verify direct factual extraction of termination notice period.",
        expected_refusal=False,
        expected_answer_contains=["30 days"],
        expected_retrieval_min_chunks=1,
        expected_retrieval_pages=[1],
        expected_retrieval_sections_contain=["Termination"],
        expected_retrieval_text_contains=["30 days"],
        expected_citation_count_min=1,
        expected_citations=[
            ExpectedCitation(page_number=1, section_contains="Termination", snippet_contains="30 days")
        ],
        expect_llm_invocation=True
    ),
    BenchmarkCase(
        case_id="FACT-002",
        category=BenchmarkCategory.DIRECT_FACT,
        question="Which state governing law applies to this contract?",
        description="Verify direct factual extraction of governing jurisdiction.",
        expected_refusal=False,
        expected_answer_contains=["Delaware"],
        expected_retrieval_min_chunks=1,
        expected_retrieval_pages=[3],
        expected_retrieval_sections_contain=["Governing Law"],
        expected_retrieval_text_contains=["Delaware"],
        expected_citation_count_min=1,
        expected_citations=[
            ExpectedCitation(page_number=3, section_contains="Governing Law")
        ],
        expect_llm_invocation=True
    ),
    BenchmarkCase(
        case_id="FACT-003",
        category=BenchmarkCategory.DIRECT_FACT,
        question="What is the aggregate liability cap under the agreement?",
        description="Verify direct factual extraction of monetary liability cap.",
        expected_refusal=False,
        expected_answer_contains=["$100,000"],
        expected_retrieval_min_chunks=1,
        expected_retrieval_pages=[2],
        expected_retrieval_sections_contain=["Limitation of Liability"],
        expected_retrieval_text_contains=["$100,000"],
        expected_citation_count_min=1,
        expected_citations=[
            ExpectedCitation(page_number=2, section_contains="Limitation of Liability")
        ],
        expect_llm_invocation=True
    ),
    BenchmarkCase(
        case_id="FACT-004",
        category=BenchmarkCategory.DIRECT_FACT,
        question="What is the cure period for a material breach of contract?",
        description="Verify direct factual extraction of breach cure window.",
        expected_refusal=False,
        expected_answer_contains=["15 days"],
        expected_retrieval_min_chunks=1,
        expected_retrieval_pages=[1],
        expected_retrieval_sections_contain=["Termination"],
        expected_retrieval_text_contains=["15 days"],
        expected_citation_count_min=1,
        expected_citations=[
            ExpectedCitation(page_number=1, section_contains="Termination")
        ],
        expect_llm_invocation=True
    ),

    # -------------------------------------------------------------
    # Category B: MULTI-CLAUSE / CONTEXT QUESTIONS
    # -------------------------------------------------------------
    BenchmarkCase(
        case_id="MULTI-001",
        category=BenchmarkCategory.MULTI_CLAUSE,
        question="What are the initial term and renewal notification requirements?",
        description="Synthesizes initial term duration (24 months) and renewal notice window (60 days).",
        expected_refusal=False,
        expected_answer_contains=["24", "60 days"],
        expected_retrieval_min_chunks=1,
        expected_retrieval_pages=[1],
        expected_retrieval_sections_contain=["Term of Agreement"],
        expected_retrieval_text_contains=["twenty-four", "60 days"],
        expected_citation_count_min=1,
        expected_citations=[
            ExpectedCitation(page_number=1, section_contains="Term of Agreement")
        ],
        expect_llm_invocation=True
    ),
    BenchmarkCase(
        case_id="MULTI-002",
        category=BenchmarkCategory.MULTI_CLAUSE,
        question="How frequently does the vendor invoice and when must client pay?",
        description="Synthesizes monthly invoicing date and 30-day payment remittance window.",
        expected_refusal=False,
        expected_answer_contains=["first calendar day", "30 days"],
        expected_retrieval_min_chunks=1,
        expected_retrieval_pages=[2],
        expected_retrieval_sections_contain=["Fees and Payment Terms"],
        expected_retrieval_text_contains=["first calendar day", "30 days"],
        expected_citation_count_min=1,
        expected_citations=[
            ExpectedCitation(page_number=2, section_contains="Fees and Payment Terms")
        ],
        expect_llm_invocation=True
    ),

    # -------------------------------------------------------------
    # Category C: UNANSWERABLE QUESTIONS
    # -------------------------------------------------------------
    BenchmarkCase(
        case_id="UNANS-001",
        category=BenchmarkCategory.UNANSWERABLE,
        question="What is the dress code policy for employees on site?",
        description="Employee dress code policy is completely absent from the commercial agreement.",
        expected_refusal=True,
        expected_answer_contains=["couldn't find enough information"],
        forbidden_answer_contains=["dress code", "business casual", "attire"],
        expected_retrieval_min_chunks=0,
        expected_retrieval_pages=[],
        expected_retrieval_sections_contain=[],
        expected_retrieval_text_contains=[],
        expected_citation_count_min=0,
        expected_citations=[],
        expect_llm_invocation=False  # Empty retrieval bypasses LLM
    ),
    BenchmarkCase(
        case_id="UNANS-002",
        category=BenchmarkCategory.UNANSWERABLE,
        question="What are the catering and food service provisions?",
        description="Food and catering provisions are absent from the commercial agreement.",
        expected_refusal=True,
        expected_answer_contains=["couldn't find enough information"],
        forbidden_answer_contains=["catering", "food", "lunch", "meals"],
        expected_retrieval_min_chunks=0,
        expected_retrieval_pages=[],
        expected_retrieval_sections_contain=[],
        expected_retrieval_text_contains=[],
        expected_citation_count_min=0,
        expected_citations=[],
        expect_llm_invocation=False  # Empty retrieval bypasses LLM
    ),
    BenchmarkCase(
        case_id="UNANS-003",
        category=BenchmarkCategory.UNANSWERABLE,
        question="What is the penalty fee if the vendor misses a project delivery deadline?",
        description="Evaluates behavior when query terms overlap slightly with general contract language but specific clause does not exist.",
        expected_refusal=True,
        expected_answer_contains=["couldn't find enough information"],
        forbidden_answer_contains=["penalty fee of", "delivery deadline penalty"],
        expected_retrieval_min_chunks=0,
        expected_retrieval_pages=[],
        expected_retrieval_sections_contain=[],
        expected_retrieval_text_contains=[],
        expected_citation_count_min=0,
        expected_citations=[],
        expect_llm_invocation=None  # May invoke LLM if similarity > 0.1, or bypass if below; either way must refuse with 0 citations
    ),
    BenchmarkCase(
        case_id="UNANS-004",
        category=BenchmarkCategory.UNANSWERABLE,
        question="What are the employee non-solicitation restrictions for the client?",
        description="Defect exposure case: Non-solicitation clause does not exist, but general contract words ('client') trigger lexical retrieval and mock hallucination without semantic confidence gate.",
        expected_refusal=True,
        expected_answer_contains=["couldn't find enough information"],
        forbidden_answer_contains=["work made for hire", "deliverables"],
        expected_retrieval_min_chunks=0,
        expected_retrieval_pages=[],
        expected_retrieval_sections_contain=[],
        expected_retrieval_text_contains=[],
        expected_citation_count_min=0,
        expected_citations=[],
        expect_llm_invocation=None
    ),

    # -------------------------------------------------------------
    # Category D: ADVERSARIAL / OUT-OF-SCOPE QUESTIONS
    # -------------------------------------------------------------
    BenchmarkCase(
        case_id="ADVERS-001",
        category=BenchmarkCategory.ADVERSARIAL,
        question="What is the protocol for launching a SpaceX rocket to Mars?",
        description="Completely unrelated topic attempting hallucination.",
        expected_refusal=True,
        expected_answer_contains=["couldn't find enough information"],
        forbidden_answer_contains=["rocket", "mars", "launch", "protocol"],
        expected_retrieval_min_chunks=0,
        expected_retrieval_pages=[],
        expected_retrieval_sections_contain=[],
        expected_retrieval_text_contains=[],
        expected_citation_count_min=0,
        expected_citations=[],
        expect_llm_invocation=False
    ),
    BenchmarkCase(
        case_id="ADVERS-002",
        category=BenchmarkCategory.ADVERSARIAL,
        question="Write a python script to calculate fibonacci numbers.",
        description="Out-of-scope non-legal code generation request.",
        expected_refusal=True,
        expected_answer_contains=["couldn't find enough information"],
        forbidden_answer_contains=["def fibonacci", "python", "fibonacci"],
        expected_retrieval_min_chunks=0,
        expected_retrieval_pages=[],
        expected_retrieval_sections_contain=[],
        expected_retrieval_text_contains=[],
        expected_citation_count_min=0,
        expected_citations=[],
        expect_llm_invocation=False
    ),

    # -------------------------------------------------------------
    # Category E: CITATION INTEGRITY CASES
    # -------------------------------------------------------------
    BenchmarkCase(
        case_id="CITE-001",
        category=BenchmarkCategory.CITATION,
        question="How long must the parties maintain confidentiality of disclosed information?",
        description="Confidentiality period (5 years) on Page 2 under Section 4 Confidentiality.",
        expected_refusal=False,
        expected_answer_contains=["five (5) years"],
        expected_retrieval_min_chunks=1,
        expected_retrieval_pages=[2],
        expected_retrieval_sections_contain=["Confidentiality"],
        expected_retrieval_text_contains=["five (5) years"],
        expected_citation_count_min=1,
        expected_citations=[
            ExpectedCitation(
                document_name="synthetic_contract.pdf",
                page_number=2,
                section_contains="Confidentiality"
            )
        ],
        expect_llm_invocation=True
    ),
    BenchmarkCase(
        case_id="CITE-002",
        category=BenchmarkCategory.CITATION,
        question="Where must binding dispute arbitration take place and under which association?",
        description="Arbitration forum in Wilmington, Delaware administered by AAA (Page 3).",
        expected_refusal=False,
        expected_answer_contains=["Wilmington", "Delaware"],
        expected_retrieval_min_chunks=1,
        expected_retrieval_pages=[3],
        expected_retrieval_sections_contain=["Dispute Resolution"],
        expected_retrieval_text_contains=["Wilmington, Delaware"],
        expected_citation_count_min=1,
        expected_citations=[
            ExpectedCitation(
                document_name="synthetic_contract.pdf",
                page_number=3,
                section_contains="Dispute Resolution"
            )
        ],
        expect_llm_invocation=True
    ),

    # -------------------------------------------------------------
    # Category F: RETRIEVAL CASES
    # -------------------------------------------------------------
    BenchmarkCase(
        case_id="RETR-001",
        category=BenchmarkCategory.RETRIEVAL,
        question="Who owns custom deliverables developed specifically for Client?",
        description="Verifies retrieval of work made for hire intellectual property clause on Page 3.",
        expected_refusal=False,
        expected_answer_contains=["Client", "work made for hire"],
        expected_retrieval_min_chunks=1,
        expected_retrieval_pages=[3],
        expected_retrieval_sections_contain=["Intellectual Property"],
        expected_retrieval_text_contains=["work made for hire"],
        expected_citation_count_min=1,
        expected_citations=[
            ExpectedCitation(page_number=3, section_contains="Intellectual Property")
        ],
        expect_llm_invocation=True
    ),
    BenchmarkCase(
        case_id="RETR-002",
        category=BenchmarkCategory.RETRIEVAL,
        question="What is the late payment fee interest rate on overdue invoices?",
        description="Verifies retrieval of late payment fee (1.5% per month) on Page 2 Section 3.",
        expected_refusal=False,
        expected_answer_contains=["1.5%"],
        expected_retrieval_min_chunks=1,
        expected_retrieval_pages=[2],
        expected_retrieval_sections_contain=["Fees and Payment Terms"],
        expected_retrieval_text_contains=["1.5%"],
        expected_citation_count_min=1,
        expected_citations=[
            ExpectedCitation(page_number=2, section_contains="Fees and Payment Terms")
        ],
        expect_llm_invocation=True
    )
]
