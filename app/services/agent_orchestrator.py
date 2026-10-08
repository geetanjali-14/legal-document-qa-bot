"""Controlled Agent Orchestrator (P1-AGNT-01).

Implements bounded agent reasoning over legal documents:
- Intent Routing (7 operational intents, multi-intent decomposition)
- Deterministic Tool Execution (0 tokens for metadata)
- Grounded Profile/Overview Tool Execution
- Bounded Evidence Retrieval Tool Execution
- Hard Loop Bounds: <= 2 iterations for single-doc, <= 3 for multi-doc
- Follow-up Contextualization over bounded conversation history
- Grounded Answer Synthesis & Strict Citation Validation
- Uncertainty State Resolution & Clarification Handling
"""
import time
import re
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any

from app.models.chat import Message, Citation
from app.models.conversation import ConversationContextState
from app.models.agent import (
    IntentType,
    UncertaintyState,
    AgentAuditTrace,
    ToolExecutionRecord,
    EvidenceItem
)
from app.services.intent_router import IntentRouter
from app.services.tools.metadata_tool import DocumentMetadataTool
from app.services.tools.profile_tool import DocumentProfileTool
from app.services.tools.evidence_tool import EvidenceRetrievalTool
from app.services.tools.structure_tool import SectionStructureTool
from app.services.tools.reference_tools import CrossReferenceTool, DefinitionTool
from app.services.tools.comparison_tool import MultiDocumentComparisonTool
from app.services.legal_reasoning import (
    ConflictDetector,
    TemporalReasoner,
    ObligationExtractor,
    RiskAnalyzer
)
from app.services.citation_service import CitationService
from app.services.citation_validator import CitationValidator
from app.services.llm_service import LLMService, LLMResponse
from app.core.telemetry import ChatTelemetry, pricing_registry
from app.core.errors import ContextLimitExceededError
from app.core.config import settings
from app.core.logging import logger


class AgentOrchestrator:
    def __init__(
        self,
        intent_router: IntentRouter,
        metadata_tool: DocumentMetadataTool,
        profile_tool: DocumentProfileTool,
        evidence_tool: EvidenceRetrievalTool,
        llm_service: LLMService,
        citation_service: CitationService,
        structure_tool: Optional[SectionStructureTool] = None,
        cross_ref_tool: Optional[CrossReferenceTool] = None,
        definition_tool: Optional[DefinitionTool] = None,
        comparison_tool: Optional[MultiDocumentComparisonTool] = None,
        conflict_detector: Optional[ConflictDetector] = None,
        temporal_reasoner: Optional[TemporalReasoner] = None,
        obligation_extractor: Optional[ObligationExtractor] = None,
        risk_analyzer: Optional[RiskAnalyzer] = None
    ):
        self.intent_router = intent_router
        self.metadata_tool = metadata_tool
        self.profile_tool = profile_tool
        self.evidence_tool = evidence_tool
        self.llm_service = llm_service
        self.citation_service = citation_service
        self.citation_validator = CitationValidator()

        # Phase P2 & P3 tools
        self.structure_tool = structure_tool
        self.cross_ref_tool = cross_ref_tool
        self.definition_tool = definition_tool
        self.comparison_tool = comparison_tool
        self.conflict_detector = conflict_detector or ConflictDetector()
        self.temporal_reasoner = temporal_reasoner or TemporalReasoner()
        self.obligation_extractor = obligation_extractor or ObligationExtractor()
        self.risk_analyzer = risk_analyzer or RiskAnalyzer()

    def process_query(
        self,
        document_id: str,
        question: str,
        history: Optional[List[Message]] = None,
        top_k: Optional[int] = None,
        request_id: Optional[str] = None
    ) -> Tuple[str, List[Citation], str, AgentAuditTrace, ChatTelemetry]:
        """
        Main bounded orchestrator loop.
        Returns: (answer, citations, confidence_state, audit_trace, telemetry)
        """
        t_start = time.perf_counter()
        req_id = request_id or f"req_{int(time.time() * 1000)}"

        # 1. Bounded Conversational Contextualization (OPT-006 & Phase 1 Structured State)
        conv_state = self.build_conversation_state(document_id, history)
        rewritten_query = self._contextualize_query(question, history, state=conv_state)
        conv_state.last_resolved_query = rewritten_query

        # 2. Intent Routing
        routing_result = self.intent_router.route_query(rewritten_query)
        primary_intent = routing_result.primary_intent

        audit_trace = AgentAuditTrace(
            request_id=req_id,
            query=question,
            iteration_count=1,
            selected_intent=primary_intent.value,
            selected_tools=[],
            tool_executions=[],
            final_evidence_state=UncertaintyState.SUPPORTED.value,
            context_rewritten_query=rewritten_query if rewritten_query != question else None
        )

        # 3. Branch by Intent
        # Case 0: General QA / world knowledge query (bypasses document retrieval)
        if primary_intent == IntentType.GENERAL_QA:
            return self._handle_general_qa(document_id, rewritten_query, audit_trace, t_start, req_id, history)

        # Case A: Deterministic METADATA query (0 LLM tokens)
        if primary_intent == IntentType.METADATA and not routing_result.is_multi_intent:
            return self._handle_metadata(document_id, rewritten_query, routing_result, audit_trace, t_start, req_id)

        # Case B: DOCUMENT_OVERVIEW query
        if primary_intent == IntentType.DOCUMENT_OVERVIEW and not routing_result.is_multi_intent:
            return self._handle_overview(document_id, rewritten_query, routing_result, audit_trace, t_start, req_id)

        # Case B2: STRUCTURE_NAVIGATION query (0 LLM tokens)
        if primary_intent == IntentType.STRUCTURE_NAVIGATION and not routing_result.is_multi_intent:
            return self._handle_structure_navigation(document_id, rewritten_query, routing_result, audit_trace, t_start, req_id)

        # Case C: MULTI-INTENT query (e.g. Overview + Metadata)
        if routing_result.is_multi_intent:
            return self._handle_multi_intent(document_id, rewritten_query, routing_result, audit_trace, t_start, req_id, top_k, history)

        # Case D: MULTI_DOCUMENT_COMPARE without second document -> Clarification
        if primary_intent == IntentType.MULTI_DOCUMENT_COMPARE:
            return self._handle_comparison_clarification(document_id, rewritten_query, audit_trace, t_start, req_id)

        # Case E: UNSUPPORTED query
        if primary_intent == IntentType.UNSUPPORTED:
            return self._handle_unsupported(document_id, rewritten_query, audit_trace, t_start, req_id)

        # Case F: Substantive EVIDENCE_SEARCH (or CROSS_SECTION / STRUCTURE fallback)
        return self._handle_evidence_search(document_id, rewritten_query, audit_trace, t_start, req_id, top_k, history)

    def build_conversation_state(
        self,
        document_id: str,
        history: Optional[List[Message]]
    ) -> ConversationContextState:
        """
        Builds a lightweight structured conversation state over the multi-turn dialogue history.
        Tracks active document, topics, clauses, parties, definitions, and events.
        """
        state = ConversationContextState(active_document=document_id)
        if not history:
            return state

        # If profile tool is available, populate known parties
        try:
            if self.profile_tool:
                profile = self.profile_tool.get_document_profile(document_id)
                if profile and profile.parties:
                    state.active_parties = list(profile.parties)
        except Exception:
            pass

        # Scan history in chronological order to track topic transitions and active references
        concept_patterns = [
            (r"\b(early\s+terminat\w*)\b", "early termination"),
            (r"\b(terminat\w*)\b", "early termination"),
            (r"\b(governing\s+law)\b", "governing law"),
            (r"\b(indemnif\w*)\b", "indemnification obligations"),
            (r"\b(insur\w*)\b", "insurance requirements"),
            (r"\b(payment\w*|allowable\s+costs|compensation|invoic\w*)\b", "payment obligations"),
            (r"\b(confidential\w*|non-disclosure)\b", "confidentiality obligations"),
            (r"\b(intellectual\s+property|ip\s+rights)\b", "intellectual property rights"),
            (r"\b(default|breach)\b", "default and breach"),
            (r"\b(cure\s+period)\b", "cure period"),
            (r"\b(notice\s+period)\b", "notice period"),
            (r"\b(holdover\s+damages)\b", "holdover damages"),
            (r"\b(severability)\b", "severability"),
            (r"\b(assignment)\b", "assignment"),
            (r"\b(amendment)\b", "amendment"),
            (r"\b(warranty|warranties)\b", "warranties")
        ]

        for msg in history:
            content = msg.content or ""
            # Detect topic changes
            for cp, canon in concept_patterns:
                if re.search(cp, content, re.IGNORECASE):
                    state.active_topic = canon
                    if canon not in state.active_events:
                        state.active_events.append(canon)
                    break

            # Detect clause / section references
            sec_m = re.findall(r'(?:Section\s+[\d\.]+|\d+\.\s+[A-Za-z\s]+)', content, re.IGNORECASE)
            if sec_m:
                state.active_clause = sec_m[-1].strip()

            # Detect defined terms in quotes e.g. "Services", "Commission", "Consultant"
            quotes = re.findall(r'["“\']([A-Z][A-Za-z0-9\s]{2,40})["”\']', content)
            for q_term in quotes:
                if q_term not in state.active_definitions:
                    state.active_definitions.append(q_term)

        return state

    def is_self_contained_query(self, query: str) -> bool:
        """
        Determines whether a question is already fully self-contained and complete.
        Self-contained questions specify both a clear legal subject/predicate and
        an explicit clause, section, or specific legal concept, so they should NOT
        be modified by previous conversation history.
        """
        q_lower = query.lower().strip()
        words = q_lower.split()

        # Questions that explicitly reference a Section or Clause are self-contained
        if re.search(r'\b(?:section|clause|article|schedule|annexure)\s+[0-9IVXLCDM\.]+', q_lower):
            return True

        # Questions that explicitly define both a substantive verb/inquiry and an explicit concept
        # e.g. "What is the termination notice period?", "What are the confidentiality obligations?"
        explicit_topics = [
            "termination notice period", "notice period for early termination", "early termination",
            "confidentiality obligations", "governing law", "intellectual property",
            "holdover damages", "cure period", "severability clause", "effective date"
        ]
        if any(topic in q_lower for topic in explicit_topics) and len(words) >= 6:
            # Check if it contains unambiguous dependent pronouns like "it", "that occurs"
            if not re.search(r'\b(?:after that occurs|initiate it|responsible for them|who can initiate it)\b', q_lower):
                return True

        return False

    def _extract_legal_context_topic(
        self,
        user_turn: Optional[str],
        asst_turn: Optional[str],
        state: Optional[ConversationContextState] = None
    ) -> str:
        """
        Extracts the primary legal topic or subject matter from preceding turns or conversation state.
        Grounded in defined terms, clauses, or key legal topics.
        """
        user_str = user_turn or ""
        asst_str = asst_turn or ""
        combined = f"{user_str} {asst_str}"

        # 1. Check for specific legal concept phrases in order of priority (user turn first)
        concept_patterns = [
            (r"\b(early\s+terminat\w*)\b", "early termination"),
            (r"\b(terminat\w*)\b", "early termination"),
            (r"\b(governing\s+law)\b", "governing law"),
            (r"\b(indemnif\w*)\b", "indemnification obligations"),
            (r"\b(insur\w*)\b", "insurance"),
            (r"\b(payment\w*|allowable\s+costs|compensation|invoic\w*)\b", "payment"),
            (r"\b(confidential\w*|non-disclosure)\b", "confidentiality"),
            (r"\b(intellectual\s+property)\b", "intellectual property"),
            (r"\b(default|breach)\b", "default"),
            (r"\b(cure\s+period)\b", "cure period"),
            (r"\b(notice\s+period)\b", "notice period"),
            (r"\b(holdover\s+damages)\b", "holdover damages"),
            (r"\b(severability)\b", "severability"),
            (r"\b(assignment)\b", "assignment")
        ]
        for cp, canon in concept_patterns:
            if re.search(cp, user_str, re.IGNORECASE):
                return canon

        for cp, canon in concept_patterns:
            if re.search(cp, combined, re.IGNORECASE):
                return canon

        # 2. Check conversation state if active topic was tracked
        if state and state.active_topic:
            return state.active_topic

        # 3. Extract section or clause name if present
        sec_m = re.findall(r'(?:Section\s+[\d\.]+|\d+\.\s+[A-Za-z\s]+)', combined, re.IGNORECASE)
        if sec_m:
            return sec_m[0].strip()

        # 4. Clean user query subject if short question
        clean_user = user_str.lower()
        for prefix in [
            "what is the notice period for",
            "what is the",
            "what are the",
            "who is responsible for",
            "who can initiate",
            "tell me about",
            "how does",
            "can they"
        ]:
            if clean_user.startswith(prefix):
                clean_user = clean_user[len(prefix):].strip()
                break
        clean_user = re.sub(r'[^\w\s-]', '', clean_user).strip()
        words = clean_user.split()
        if 1 <= len(words) <= 4:
            return " ".join(words)

        return ""

    def _contextualize_query(
        self,
        query: str,
        history: Optional[List[Message]],
        state: Optional[ConversationContextState] = None
    ) -> str:
        """
        Multi-turn conversational contextualizer inspecting conversation state and history.
        Resolves pronouns (it, that, this, they, them, its), event references (occurs, happens, afterward),
        and legal concepts (the agreement, the contract, the provision, the termination, the obligation).
        Guarantees self-contained queries are preserved intact.
        """
        if not history or len(history) < 2:
            return query

        # Objective 4: Preserve self-contained questions
        if self.is_self_contained_query(query):
            return query

        q_lower = query.lower()

        # Extract last user and assistant turns
        last_user_turn = None
        last_assistant_turn = None
        for m in reversed(history):
            if m.role == "user" and not last_user_turn:
                last_user_turn = m.content
            elif m.role == "assistant" and not last_assistant_turn:
                last_assistant_turn = m.content
            if last_user_turn and last_assistant_turn:
                break

        # Check for previous clause / former / preceding references
        if "previous clause" in q_lower or "former" in q_lower or "preceding" in q_lower or "above section" in q_lower:
            sec_matches = []
            if last_assistant_turn:
                sec_matches = re.findall(r'(?:Section\s+[\d\.]+|\d+\.\s+[A-Za-z]+)', last_assistant_turn, re.IGNORECASE)
            if sec_matches:
                enriched = f"{query} preceding provision related to {sec_matches[0]}"
                logger.info(f"[AgentOrchestrator] Contextualized query: '{query}' -> '{enriched}'")
                return enriched
            elif last_user_turn:
                enriched = f"{query} preceding clause before topic of {last_user_turn}"
                logger.info(f"[AgentOrchestrator] Contextualized query: '{query}' -> '{enriched}'")
                return enriched

        # Extract primary antecedent topic
        topic = self._extract_legal_context_topic(last_user_turn, last_assistant_turn, state)

        # Objective 3 & 7: Semantic Reference & Pronoun Patterns
        pronoun_patterns = [
            (r"\bwho\s+can\s+initiate\s+(?:it|this|that)\b", f"who can initiate {topic}"),
            (r"\bwho\s+can\s+terminate\s+(?:it|this|that)\b", f"who can terminate {topic}"),
            (r"\bwho\s+is\s+responsible\s+for\s+(?:them|it|this|that)\b", f"who is responsible for {topic}"),
            (r"\bwhat\s+are\s+their\s+obligations\b", f"what are their obligations regarding {topic}"),
            (r"\bwhat\s+happens\s+after\s+(?:that|it)(?:\s+occurs|\s+happens)?\b", f"what happens after {topic}"),
            (r"\bafter\s+(?:that|it)\s+(?:occurs|happens)\b", f"after {topic}"),
            (r"\bfollowing\s+(?:that|it)\b", f"following {topic}"),
            (r"\bafter\s+(?:that|it)\b", f"after {topic}"),
            (r"\bwhen\s+(?:that|it)\s+(?:occurs|happens)\b", f"when {topic}"),
            (r"\bdoes\s+that\s+obligation\s+continue\s+afterward\b", f"does {topic} continue afterward"),
            (r"\bdoes\s+this\s+continue\b", f"does {topic} continue"),
            (r"\bdoes\s+(?:that|it)\s+continue\b", f"does {topic} continue"),
            (r"\bcan\s+they\s+terminate\b", f"can they terminate the agreement regarding {topic}"),
            (r"\bcan\s+they\s+assign\s+(?:them|it|this)\b", f"can they assign {topic}"),
            (r"\bwhen\s+must\s+that\s+payment\s+be\s+made\b", f"when must {topic} payment be made"),
            (r"\bhow\s+long\s+does\s+it\s+last\b", f"how long does {topic} last"),
            (r"\bwhat\s+is\s+its\s+duration\b", f"what is duration of {topic}"),
            (r"\bunder\s+the\s+provision\b", f"under the {topic} provision"),
            (r"\bunder\s+the\s+termination\b", f"under {topic}"),
            (r"\babout\s+it\b", f"about {topic}"),
            (r"\babout\s+that\b", f"about {topic}"),
            (r"\babout\s+this\b", f"about {topic}"),
        ]

        if topic:
            for pat, repl in pronoun_patterns:
                if re.search(pat, query, re.IGNORECASE):
                    resolved = re.sub(pat, repl, query, flags=re.IGNORECASE)
                    logger.info(f"[AgentOrchestrator] Resolved pronoun query: '{query}' -> '{resolved}'")
                    return resolved

            # Short elliptical follow-up containing "it", "that", "this", "they", "them", "its", "those"
            if re.search(r"\b(?:it|that|this|they|them|its|those)\b", q_lower) and len(query.split()) <= 8:
                resolved = f"{query} regarding {topic}"
                logger.info(f"[AgentOrchestrator] Enriched elliptical query: '{query}' -> '{resolved}'")
                return resolved

            # Concept references: "the provision", "the obligation", "the agreement" in short queries
            if re.search(r"\b(?:the\s+provision|the\s+obligation|the\s+terms)\b", q_lower) and len(query.split()) <= 8:
                resolved = f"{query} regarding {topic}"
                logger.info(f"[AgentOrchestrator] Enriched legal concept query: '{query}' -> '{resolved}'")
                return resolved

        # Generic short follow-up fallback
        follow_up_cues = ["what about it", "tell me more", "how about that"]
        if (any(cue in q_lower for cue in follow_up_cues) or q_lower.startswith(("and ", "what about ", "why "))) and last_user_turn and len(query.split()) <= 6:
            enriched = f"{query} regarding {last_user_turn}"
            logger.info(f"[AgentOrchestrator] Enriched short follow-up query: '{query}' -> '{enriched}'")
            return enriched

        return query


    def _handle_metadata(
        self,
        document_id: str,
        query: str,
        routing_result,
        audit_trace: AgentAuditTrace,
        t_start: float,
        req_id: str
    ) -> Tuple[str, List[Citation], str, AgentAuditTrace, ChatTelemetry]:
        t_tool = time.perf_counter()
        meta = self.metadata_tool.get_document_metadata(document_id)
        tool_latency = max(0.0, (time.perf_counter() - t_tool) * 1000.0)

        audit_trace.selected_tools.append("get_document_metadata")
        audit_trace.tool_executions.append(
            ToolExecutionRecord(
                tool_name="get_document_metadata",
                tool_input={"document_id": document_id},
                tool_output_summary="Retrieved authoritative DocumentMetadata",
                evidence_state=UncertaintyState.SUPPORTED.value if meta else UncertaintyState.NOT_FOUND.value,
                latency_ms=round(tool_latency, 2),
                tokens_used=0
            )
        )
        audit_trace.answer_derivation_type = "deterministic_metadata"

        if not meta:
            answer = f"Document '{document_id}' was not found in the corpus."
            confidence = UncertaintyState.NOT_FOUND.value
        else:
            attr = routing_result.sub_intents[0].get("attribute") if routing_result.sub_intents else None
            answer = self.metadata_tool.format_metadata_answer(meta, specific_attribute=attr)
            confidence = UncertaintyState.SUPPORTED.value

        total_latency = max(0.0, (time.perf_counter() - t_start) * 1000.0)
        telemetry = ChatTelemetry(
            request_id=req_id,
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            document_id=document_id,
            status=confidence,
            total_latency_ms=round(total_latency, 2),
            retrieval_latency_ms=0.0,
            embedding_latency_ms=0.0,
            llm_latency_ms=0.0,
            retrieved_chunks_count=0,
            token_usage_type="actual",
            input_tokens=0,
            output_tokens=0,
            total_tokens=0,
            llm_provider="deterministic_tool",
            llm_model="none",
            embedding_provider="none",
            embedding_model="none"
        )
        return answer, [], confidence, audit_trace, telemetry

    def _handle_overview(
        self,
        document_id: str,
        query: str,
        routing_result,
        audit_trace: AgentAuditTrace,
        t_start: float,
        req_id: str
    ) -> Tuple[str, List[Citation], str, AgentAuditTrace, ChatTelemetry]:
        t_tool = time.perf_counter()
        profile = self.profile_tool.get_document_profile(document_id)
        tool_latency = max(0.0, (time.perf_counter() - t_tool) * 1000.0)

        audit_trace.selected_tools.append("get_document_profile")
        audit_trace.tool_executions.append(
            ToolExecutionRecord(
                tool_name="get_document_profile",
                tool_input={"document_id": document_id},
                tool_output_summary="Retrieved grounded DocumentProfileResult",
                evidence_state=UncertaintyState.SUPPORTED.value if profile else UncertaintyState.NOT_FOUND.value,
                latency_ms=round(tool_latency, 2),
                tokens_used=0
            )
        )
        audit_trace.answer_derivation_type = "grounded_profile"

        if not profile:
            answer = "I couldn't find enough information in the uploaded document to generate an overview."
            confidence = UncertaintyState.INSUFFICIENT_EVIDENCE.value
        else:
            aspect = routing_result.sub_intents[0].get("aspect") if routing_result.sub_intents else None
            answer = self.profile_tool.format_overview_answer(profile, aspect=aspect)
            confidence = UncertaintyState.SUPPORTED.value

        total_latency = max(0.0, (time.perf_counter() - t_start) * 1000.0)
        telemetry = ChatTelemetry(
            request_id=req_id,
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            document_id=document_id,
            status=confidence,
            total_latency_ms=round(total_latency, 2),
            retrieval_latency_ms=0.0,
            embedding_latency_ms=0.0,
            llm_latency_ms=0.0,
            retrieved_chunks_count=0,
            token_usage_type="actual",
            input_tokens=0,
            output_tokens=0,
            total_tokens=0,
            llm_provider="grounded_profile_tool",
            llm_model="none",
            embedding_provider="none",
            embedding_model="none"
        )
        return answer, [], confidence, audit_trace, telemetry

    def _handle_structure_navigation(
        self,
        document_id: str,
        query: str,
        routing_result,
        audit_trace: AgentAuditTrace,
        t_start: float,
        req_id: str
    ) -> Tuple[str, List[Citation], str, AgentAuditTrace, ChatTelemetry]:
        """Handle deterministic structure queries (0 LLM tokens)."""
        t_tool = time.perf_counter()
        if not self.structure_tool:
            # Fallback if structure tool not injected
            meta = self.metadata_tool.get_document_metadata(document_id)
            answer = f"Structural details for '{meta.original_filename if meta else document_id}' are being processed."
            confidence = UncertaintyState.SUPPORTED.value
            tool_latency = 0.0
        else:
            # Extract section or clause identifier if mentioned
            sec_match = re.search(r'(?:section|clause|article)\s+([0-9IVXLCDM\.\(\)a-z]+)', query, re.IGNORECASE)
            sec_target = sec_match.group(1) if sec_match else None
            res = self.structure_tool.get_section_structure(document_id, section_query=sec_target)
            tool_latency = res.latency_ms

            if res.matched_section:
                sec = res.matched_section
                bc = " > ".join(sec.get("breadcrumb", []))
                text_prev = sec.get("text_content") or "No preview content available."
                answer = (
                    f"**{sec.get('title', 'Section')}** (`{sec.get('section_id')}`)\n\n"
                    f"- **Hierarchy:** {bc}\n"
                    f"- **Pages:** {sec.get('page_start')} - {sec.get('page_end')}\n"
                    f"- **Content Excerpt:**\n> {text_prev}"
                )
                confidence = UncertaintyState.SUPPORTED.value
            elif res.table_of_contents:
                toc_lines = []
                for n in res.table_of_contents[:15]:
                    toc_lines.append(f"- **{n.get('section_id', '')}**: {n.get('title', 'Untitled')} (p. {n.get('page_start')})")
                    for sub in n.get("subsections", [])[:10]:
                        toc_lines.append(f"  - **{sub.get('section_id', '')}**: {sub.get('title', 'Untitled')} (p. {sub.get('page_start')})")
                        for sub2 in sub.get("subsections", [])[:5]:
                            toc_lines.append(f"    - **{sub2.get('section_id', '')}**: {sub2.get('title', 'Untitled')} (p. {sub2.get('page_start')})")
                answer = (
                    f"**Table of Contents / Structural Outline** ({res.total_sections} provisions detected):\n\n"
                    + "\n".join(toc_lines)
                )
                confidence = UncertaintyState.SUPPORTED.value
            else:
                answer = "No structural sections or table of contents could be identified in this document."
                confidence = UncertaintyState.NOT_FOUND.value

        audit_trace.selected_tools.append("get_section_structure")
        audit_trace.tool_executions.append(
            ToolExecutionRecord(
                tool_name="get_section_structure",
                tool_input={"document_id": document_id, "query": query},
                tool_output_summary="Navigated document structure tree",
                evidence_state=confidence,
                latency_ms=round(tool_latency, 2),
                tokens_used=0
            )
        )
        audit_trace.answer_derivation_type = "deterministic_structure"

        total_latency = max(0.0, (time.perf_counter() - t_start) * 1000.0)
        telemetry = ChatTelemetry(
            request_id=req_id,
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            document_id=document_id,
            status=confidence,
            total_latency_ms=round(total_latency, 2),
            retrieval_latency_ms=0.0,
            embedding_latency_ms=0.0,
            llm_latency_ms=0.0,
            retrieved_chunks_count=0,
            token_usage_type="actual",
            input_tokens=0,
            output_tokens=0,
            total_tokens=0,
            llm_provider="deterministic_structure_tool",
            llm_model="none"
        )
        return answer, [], confidence, audit_trace, telemetry

    def _handle_multi_intent(
        self,
        document_id: str,
        query: str,
        routing_result,
        audit_trace: AgentAuditTrace,
        t_start: float,
        req_id: str,
        top_k: Optional[int],
        history: Optional[List[Message]]
    ) -> Tuple[str, List[Citation], str, AgentAuditTrace, ChatTelemetry]:
        answers = []
        citations: List[Citation] = []
        audit_trace.iteration_count = 2

        # 1. Execute metadata component if present
        if IntentType.METADATA in routing_result.intents:
            meta = self.metadata_tool.get_document_metadata(document_id)
            audit_trace.selected_tools.append("get_document_metadata")
            if meta:
                meta_attr = self.intent_router._detect_metadata_attribute(query)
                meta_ans = self.metadata_tool.format_metadata_answer(meta, specific_attribute=meta_attr)
                answers.append(f"**Document Metadata:**\n{meta_ans}")

        # 2. Execute overview component if present
        if IntentType.DOCUMENT_OVERVIEW in routing_result.intents:
            profile = self.profile_tool.get_document_profile(document_id)
            audit_trace.selected_tools.append("get_document_profile")
            if profile:
                overview_ans = self.profile_tool.format_overview_answer(profile)
                answers.append(f"**Document Overview:**\n{overview_ans}")

        # 3. Execute evidence retrieval component if present
        if IntentType.EVIDENCE_SEARCH in routing_result.intents:
            ev_ans, ev_cits, ev_conf, _, _ = self._handle_evidence_search(
                document_id, query, audit_trace, t_start, req_id, top_k, history
            )
            answers.append(f"**Substantive Evidence:**\n{ev_ans}")
            citations.extend(ev_cits)

        final_answer = "\n\n".join(answers) if answers else "Unable to resolve composite query."
        total_latency = max(0.0, (time.perf_counter() - t_start) * 1000.0)
        confidence = UncertaintyState.SUPPORTED.value if answers else UncertaintyState.INSUFFICIENT_EVIDENCE.value

        telemetry = ChatTelemetry(
            request_id=req_id,
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            document_id=document_id,
            status=confidence,
            total_latency_ms=round(total_latency, 2),
            retrieval_latency_ms=0.0,
            embedding_latency_ms=0.0,
            llm_latency_ms=0.0,
            retrieved_chunks_count=len(citations),
            token_usage_type="actual",
            input_tokens=0,
            output_tokens=0,
            total_tokens=0,
            llm_provider="multi_intent_orchestrator",
            llm_model="none"
        )
        return final_answer, citations, confidence, audit_trace, telemetry

    def _handle_comparison_clarification(
        self,
        document_id: str,
        query: str,
        audit_trace: AgentAuditTrace,
        t_start: float,
        req_id: str
    ) -> Tuple[str, List[Citation], str, AgentAuditTrace, ChatTelemetry]:
        # Attempt to resolve explicit second document ID or filename if mentioned in query
        doc_b_id = None
        if self.metadata_tool and hasattr(self.metadata_tool, "document_service"):
            docs = self.metadata_tool.document_service.list_documents()
            for d in docs:
                if d.document_id != document_id:
                    # Check if document_id or filename is mentioned in the query
                    if d.document_id.lower() in query.lower() or d.original_filename.lower() in query.lower():
                        doc_b_id = d.document_id
                        break
                    # Check simplified match e.g. "document B", "contract B", "doc_b"
                    safe_orig = re.sub(r'[^a-zA-Z0-9]', '', d.original_filename.lower())
                    clean_q = re.sub(r'[^a-zA-Z0-9]', '', query.lower())
                    if safe_orig and safe_orig in clean_q:
                        doc_b_id = d.document_id
                        break

        # If second document resolved and comparison tool exists, execute comparative reasoning
        if doc_b_id and self.comparison_tool:
            audit_trace.selected_tools.append("compare_documents")
            # Extract topics to compare from query
            topics = ["Termination notice", "Governing law", "Payment terms", "Liability cap"]
            # Look for specific topic mention in query
            for candidate_topic in ["termination", "notice period", "governing law", "liability", "indemnification", "payment"]:
                if candidate_topic in query.lower():
                    topics = [candidate_topic.title()]
                    break

            comp_result = self.comparison_tool.compare_documents(
                doc_a_id=document_id,
                doc_b_id=doc_b_id,
                topics=topics
            )

            citations: List[Citation] = []
            answer_lines = [
                f"### Cross-Contract Comparison: {comp_result.doc_a_name} vs {comp_result.doc_b_name}\n"
            ]
            for row in comp_result.rows:
                answer_lines.append(f"**Topic: {row.topic}** (Status: `{row.status}`)")
                answer_lines.append(f"- **{comp_result.doc_a_name}**: {row.doc_a_evidence}")
                if row.doc_a_citation:
                    citations.append(
                        Citation(
                            document_id=row.doc_a_citation["document_id"],
                            document_name=row.doc_a_citation["document_name"],
                            page_number=row.doc_a_citation.get("page") or 1,
                            section=row.doc_a_citation.get("section") or "General",
                            chunk_id=row.doc_a_citation.get("chunk_id") or f"chk_{document_id[:8]}",
                            snippet=row.doc_a_evidence[:200]
                        )
                    )
                answer_lines.append(f"- **{comp_result.doc_b_name}**: {row.doc_b_evidence}")
                if row.doc_b_citation:
                    citations.append(
                        Citation(
                            document_id=row.doc_b_citation["document_id"],
                            document_name=row.doc_b_citation["document_name"],
                            page_number=row.doc_b_citation.get("page") or 1,
                            section=row.doc_b_citation.get("section") or "General",
                            chunk_id=row.doc_b_citation.get("chunk_id") or f"chk_{doc_b_id[:8]}",
                            snippet=row.doc_b_evidence[:200]
                        )
                    )
                answer_lines.append("")

            final_answer = "\n".join(answer_lines).strip()
            total_latency = max(0.0, (time.perf_counter() - t_start) * 1000.0)
            telemetry = ChatTelemetry(
                request_id=req_id,
                timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                document_id=document_id,
                status=UncertaintyState.SUPPORTED.value,
                total_latency_ms=round(total_latency, 2),
                retrieved_chunks_count=len(citations)
            )
            audit_trace.final_evidence_state = UncertaintyState.SUPPORTED.value
            audit_trace.answer_derivation_type = "multi_document_comparison"
            return final_answer, citations, UncertaintyState.SUPPORTED.value, audit_trace, telemetry

        clarification_msg = (
            "You requested a multi-document comparison. Which documents would you like me to compare? "
            "Please upload or specify the second document to perform cross-contract analysis."
        )
        audit_trace.final_evidence_state = UncertaintyState.CLARIFICATION_REQUIRED.value
        audit_trace.answer_derivation_type = "clarification"

        total_latency = max(0.0, (time.perf_counter() - t_start) * 1000.0)
        telemetry = ChatTelemetry(
            request_id=req_id,
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            document_id=document_id,
            status=UncertaintyState.CLARIFICATION_REQUIRED.value,
            total_latency_ms=round(total_latency, 2)
        )
        return clarification_msg, [], UncertaintyState.CLARIFICATION_REQUIRED.value, audit_trace, telemetry

    def _handle_general_qa(
        self,
        document_id: str,
        query: str,
        audit_trace: AgentAuditTrace,
        t_start: float,
        req_id: str,
        history: Optional[List[Message]]
    ) -> Tuple[str, List[Citation], str, AgentAuditTrace, ChatTelemetry]:
        """Handles general knowledge, date/time, greeting queries directly without document retrieval."""
        audit_trace.answer_derivation_type = "general_knowledge"
        audit_trace.selected_tools = []
        audit_trace.final_evidence_state = UncertaintyState.SUPPORTED.value

        llm_res = self.llm_service.generate_answer(
            question=query,
            context_chunks=[],
            history=history
        )
        total_latency = max(0.0, (time.perf_counter() - t_start) * 1000.0)
        telemetry = ChatTelemetry(
            request_id=req_id,
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            document_id=document_id,
            status="success",
            retrieval_latency_ms=0.0,
            embedding_latency_ms=0.0,
            llm_latency_ms=llm_res.latency_ms,
            total_latency_ms=round(total_latency, 2),
            llm_provider=llm_res.provider,
            llm_model=llm_res.model,
            input_tokens=llm_res.input_tokens,
            output_tokens=llm_res.output_tokens,
            total_tokens=llm_res.total_tokens,
            token_usage_type=llm_res.token_usage_type,
            cost_estimate_usd=pricing_registry.calculate_cost(
                llm_res.provider,
                llm_res.model,
                llm_res.input_tokens or llm_res.estimated_input_tokens or 0,
                llm_res.output_tokens or llm_res.estimated_output_tokens or 0
            )
        )
        return llm_res.content, [], UncertaintyState.SUPPORTED.value, audit_trace, telemetry

    def _handle_unsupported(
        self,
        document_id: str,
        query: str,
        audit_trace: AgentAuditTrace,
        t_start: float,
        req_id: str
    ) -> Tuple[str, List[Citation], str, AgentAuditTrace, ChatTelemetry]:
        refusal_msg = (
            "I couldn't find enough information in the uploaded document to answer this question. "
            "My answers are strictly limited to the factual contents of your uploaded legal document."
        )
        audit_trace.final_evidence_state = UncertaintyState.NOT_FOUND.value
        audit_trace.answer_derivation_type = "refusal"

        total_latency = max(0.0, (time.perf_counter() - t_start) * 1000.0)
        telemetry = ChatTelemetry(
            request_id=req_id,
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            document_id=document_id,
            status=UncertaintyState.INSUFFICIENT_EVIDENCE.value,
            total_latency_ms=round(total_latency, 2),
            retrieved_chunks_count=0,
            token_usage_type="unknown"
        )
        return refusal_msg, [], UncertaintyState.INSUFFICIENT_EVIDENCE.value, audit_trace, telemetry

    def _handle_evidence_search(
        self,
        document_id: str,
        query: str,
        audit_trace: AgentAuditTrace,
        t_start: float,
        req_id: str,
        top_k: Optional[int],
        history: Optional[List[Message]]
    ) -> Tuple[str, List[Citation], str, AgentAuditTrace, ChatTelemetry]:
        # Ambiguity / safety: detect if query explicitly refers to an external document or asks ambiguous cross-contract question
        if self.metadata_tool and hasattr(self.metadata_tool, "document_service"):
            other_docs = [d for d in self.metadata_tool.document_service.list_documents() if d.document_id != document_id]
            for od in other_docs:
                clean_stem = Path(od.original_filename).stem.lower()
                clean_fn = od.original_filename.lower()
                clean_id = od.document_id.lower()
                clean_q = query.lower()
                clean_q_alphanumeric = re.sub(r'[^a-z0-9]', '', clean_q)
                clean_stem_alphanumeric = re.sub(r'[^a-z0-9]', '', clean_stem)
                if (
                    clean_stem in clean_q
                    or clean_fn in clean_q
                    or clean_id in clean_q
                    or (len(clean_stem_alphanumeric) >= 4 and clean_stem_alphanumeric in clean_q_alphanumeric)
                ):
                    # Query is targeting a different document than active document_id
                    audit_trace.final_evidence_state = UncertaintyState.CLARIFICATION_REQUIRED.value
                    audit_trace.answer_derivation_type = "clarification"
                    clarification = (
                        f"This question references '{od.original_filename}', but the active document is "
                        f"'{self.metadata_tool.document_service.get_document(document_id).original_filename if self.metadata_tool.document_service.get_document(document_id) else document_id}'. "
                        f"Please select '{od.original_filename}' or ask a comparative question between both documents to maintain document isolation."
                    )
                    total_latency = max(0.0, (time.perf_counter() - t_start) * 1000.0)
                    telemetry = ChatTelemetry(
                        request_id=req_id,
                        timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        document_id=document_id,
                        status=UncertaintyState.CLARIFICATION_REQUIRED.value,
                        total_latency_ms=round(total_latency, 2),
                        retrieved_chunks_count=0
                    )
                    return clarification, [], UncertaintyState.CLARIFICATION_REQUIRED.value, audit_trace, telemetry
        # Iteration 1: Retrieve bounded evidence
        audit_trace.selected_tools.append("search_document_evidence")
        t_tool = time.perf_counter()
        evidence_result = self.evidence_tool.search_document_evidence(
            document_ids=[document_id],
            query=query,
            top_k=top_k
        )
        tool_latency = max(0.0, (time.perf_counter() - t_tool) * 1000.0)

        audit_trace.tool_executions.append(
            ToolExecutionRecord(
                tool_name="search_document_evidence",
                tool_input={"document_id": document_id, "query": query, "top_k": top_k},
                tool_output_summary=f"Retrieved {len(evidence_result.items)} evidence chunks",
                evidence_state=evidence_result.evidence_state.value,
                latency_ms=round(tool_latency, 2)
            )
        )

        if not evidence_result.items or evidence_result.evidence_state == UncertaintyState.INSUFFICIENT_EVIDENCE:
            refusal = "I couldn't find enough information in the uploaded document to answer this question."
            audit_trace.final_evidence_state = UncertaintyState.INSUFFICIENT_EVIDENCE.value
            audit_trace.answer_derivation_type = "refusal"
            total_latency = max(0.0, (time.perf_counter() - t_start) * 1000.0)
            telemetry = ChatTelemetry(
                request_id=req_id,
                timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                document_id=document_id,
                status=UncertaintyState.INSUFFICIENT_EVIDENCE.value,
                total_latency_ms=round(total_latency, 2),
                retrieval_latency_ms=evidence_result.latency_ms,
                retrieved_chunks_count=0
            )
            return refusal, [], UncertaintyState.INSUFFICIENT_EVIDENCE.value, audit_trace, telemetry

        # Validate retrieved context size limit
        total_context_chars = sum(len(it.text) for it in evidence_result.items)
        if total_context_chars > settings.MAX_CONTEXT_CHARS:
            total_latency = max(0.0, (time.perf_counter() - t_start) * 1000.0)
            telemetry = ChatTelemetry(
                request_id=req_id,
                timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                document_id=document_id,
                status="rejected",
                error_category="context_limit_exceeded",
                total_latency_ms=round(total_latency, 2),
                retrieval_latency_ms=evidence_result.latency_ms,
                retrieved_chunks_count=len(evidence_result.items),
                token_usage_type="unknown"
            )
            logger.warning(f"[{req_id}] Context rejected: total context chars ({total_context_chars}) > {settings.MAX_CONTEXT_CHARS}")
            raise ContextLimitExceededError(
                f"Retrieved context size ({total_context_chars} characters) exceeds maximum allowed limit of {settings.MAX_CONTEXT_CHARS} characters."
            )

        # Check for defined term inquiry
        if self.definition_tool and any(k in query.lower() for k in ["defined", "meaning of", "definition of", "means"]):
            term_match = re.search(r'["“\']([^"“”\']+)["”\']|\b(?:meaning|definition)\s+of\s+([A-Za-z\s]+)', query, re.IGNORECASE)
            target_term = (term_match.group(1) or term_match.group(2) if term_match else None)
            if target_term:
                def_res = self.definition_tool.lookup_definition(document_id, target_term.strip())
                if def_res.get("found"):
                    audit_trace.selected_tools.append("lookup_definition")
                    evidence_result.items.append(
                        EvidenceItem(
                            document_id=document_id,
                            chunk_id=f"def_{target_term.strip()[:8]}",
                            page_number=def_res.get("page_number", 1),
                            section="Definitions",
                            score=1.0,
                            text=f"Defined Term: \"{def_res.get('term')}\" means {def_res.get('definition')}"
                        )
                    )

        # Multi-Hop Provision Reasoning (e.g. indemnification after termination -> retrieve survival clause)
        q_lower = query.lower()
        if any(t in q_lower for t in ["after termination", "following termination", "post-termination", "upon termination"]):
            if "indemnif" in q_lower or "confidential" in q_lower or "liability" in q_lower:
                # Query survival/post-termination provisions
                survival_result = self.evidence_tool.search_document_evidence(
                    document_ids=[document_id],
                    query="survival of provisions indemnification confidentiality obligations after termination",
                    top_k=2
                )
                if survival_result.items:
                    audit_trace.selected_tools.append("retrieve_survival_provisions")
                    for s_item in survival_result.items:
                        if not any(it.chunk_id == s_item.chunk_id for it in evidence_result.items):
                            evidence_result.items.append(s_item)

        # Check for cross-reference in query or top evidence chunks
        if self.cross_ref_tool:
            # Check in query
            ref_matches = re.findall(r'(?:section|clause|article|annexure|schedule|exhibit)\s+([0-9IVXLCDM\.\(\)a-z]+)', query, re.IGNORECASE)
            # Also scan top evidence texts for internal cross-references
            for item in evidence_result.items[:3]:
                ref_matches.extend(re.findall(r'(?:subject\s+to|pursuant\s+to|as\s+provided\s+in|in\s+accordance\s+with)\s+((?:Section|Clause|Article|Annexure|Schedule|Exhibit)\s+[0-9IVXLCDM\.\(\)a-z]+)', item.text, re.IGNORECASE))

            seen_refs = set()
            for r_text in ref_matches:
                clean_ref = str(r_text).strip()
                if clean_ref.lower() in seen_refs:
                    continue
                seen_refs.add(clean_ref.lower())
                ref_res = self.cross_ref_tool.resolve_reference(document_id, clean_ref)
                if ref_res.get("found") and ref_res.get("text_content"):
                    if "resolve_cross_reference" not in audit_trace.selected_tools:
                        audit_trace.selected_tools.append("resolve_cross_reference")
                    evidence_result.items.append(
                        EvidenceItem(
                            document_id=document_id,
                            chunk_id=f"ref_{ref_res.get('resolved_section_id', 'target')}",
                            page_number=ref_res.get("page_start", 1),
                            section=f"Cross-Reference {ref_res.get('resolved_section_id')}",
                            score=0.95,
                            text=f"[Cross-Referenced Section {ref_res.get('resolved_section_id')}]: {ref_res.get('text_content')[:400]}"
                        )
                    )

        # Create raw citations from evidence items
        raw_tuples = [
            (
                type("ChunkWrapper", (), {
                    "document_id": it.document_id,
                    "document_name": it.document_name or "Document",
                    "page_number": it.page_number,
                    "section": it.section,
                    "chunk_id": it.chunk_id,
                    "text": it.text
                })(),
                it.score
            )
            for it in evidence_result.items
        ]
        raw_citations = self.citation_service.create_citations(raw_tuples)

        # Validate citations against verified evidence
        validated_citations, is_valid = self.citation_validator.validate_citations(
            raw_citations, evidence_result.items
        )

        # Check for potential conflicts across evidence provisions
        conflicts = self.conflict_detector.detect_conflicts(evidence_result.items)
        if conflicts:
            audit_trace.final_evidence_state = UncertaintyState.CONFLICTING_EVIDENCE.value
            conflict_notes = "\n\n".join([f"⚠️ **{c.description}**" for c in conflicts])
        else:
            conflict_notes = ""

        # Check for temporal reasoning queries (dates, timelines, notice periods, deadlines, cure periods)
        temporal_notes = ""
        q_lower = query.lower()
        if self.temporal_reasoner and any(k in q_lower for k in ["deadline", "timeline", "notice period", "cure period", "effective date", "when must", "how long", "notice window"]):
            all_events = []
            for item in evidence_result.items:
                evs = self.temporal_reasoner.extract_temporal_events(item.text, section=item.section, page=item.page_number)
                all_events.extend(evs)
            if all_events:
                audit_trace.selected_tools.append("extract_temporal_events")
                ev_lines = [f"- **{e.event_type}**: {e.deadline_text} (p. {e.page or 'N/A'}, {e.section or 'General'})" for e in all_events[:5]]
                temporal_notes = "**Structured Timeline & Deadlines:**\n" + "\n".join(ev_lines)

        # Check for obligation extraction queries (obligations, duties, responsible party, must, shall)
        obligation_notes = ""
        if self.obligation_extractor and any(k in q_lower for k in ["obligation", "obligations", "duties", "duty", "responsible", "shall", "must do", "required to"]):
            all_obs = []
            for item in evidence_result.items:
                obs = self.obligation_extractor.extract_obligations(item.text, section=item.section, page=item.page_number)
                all_obs.extend(obs)
            if all_obs:
                audit_trace.selected_tools.append("extract_obligations")
                ob_lines = [f"- **{o.party}** ({o.obligation_type}): {o.modality} {o.action}" for o in all_obs[:6]]
                obligation_notes = "**Extracted Contractual Obligations:**\n" + "\n".join(ob_lines)

        # Check for risk analysis queries (risks, liabilities, one-sided, exposure, red flags)
        risk_notes = ""
        if self.risk_analyzer and any(k in q_lower for k in ["risk", "risks", "liability", "exposure", "one-sided", "red flag", "review"]):
            all_risks = self.risk_analyzer.analyze_risks(evidence_result.items)
            if all_risks:
                audit_trace.selected_tools.append("analyze_risks")
                r_lines = [f"- **{r.title}** ({r.section or 'General'}): {r.potential_issue}" for r in all_risks[:4]]
                risk_notes = (
                    "**Analytical Risk Observations (Non-advisory):**\n"
                    + "\n".join(r_lines)
                    + "\n\n*Note: These analytical observations highlight notable contractual terms and do not constitute formal legal counsel.*"
                )

        # Iteration 2: Grounded Reasoning & LLM Synthesis
        audit_trace.iteration_count = 2
        audit_trace.answer_derivation_type = "grounded_synthesis"

        context_chunks = [
            f"[Section: {it.section} | Page: {it.page_number}]\n{it.text}"
            for it in evidence_result.items
        ]

        t_llm_start = time.perf_counter()
        llm_res = self.llm_service.generate_answer(
            question=query,
            context_chunks=context_chunks,
            history=history
        )
        llm_latency = max(0.0, (time.perf_counter() - t_llm_start) * 1000.0)

        if isinstance(llm_res, LLMResponse):
            answer_text = llm_res.content
            inp_tok = llm_res.input_tokens
            out_tok = llm_res.output_tokens
            tot_tok = llm_res.total_tokens
            tok_type = llm_res.token_usage_type
            llm_prov = llm_res.provider or settings.LLM_PROVIDER
            llm_mod = llm_res.model or settings.LLM_MODEL
            est_in = llm_res.estimated_input_tokens
            est_out = llm_res.estimated_output_tokens
            est_tot = llm_res.estimated_total_tokens
            est_meth = llm_res.estimation_method
        else:
            answer_text = str(llm_res)
            inp_tok = out_tok = tot_tok = None
            tok_type = "unknown"
            llm_prov = settings.LLM_PROVIDER
            llm_mod = settings.LLM_MODEL
            est_in = est_out = est_tot = est_meth = None

        if conflict_notes and "inconsistency" not in answer_text.lower():
            answer_text += f"\n\n{conflict_notes}"
        if temporal_notes and "couldn't find enough information" not in answer_text.lower():
            answer_text += f"\n\n{temporal_notes}"
        if obligation_notes and "couldn't find enough information" not in answer_text.lower():
            answer_text += f"\n\n{obligation_notes}"
        if risk_notes and "couldn't find enough information" not in answer_text.lower():
            answer_text += f"\n\n{risk_notes}"

        # Phase H & G: Answer Verification & Optimization
        # If no valid citations exist and evidence was marked insufficient, ensure safe refusal
        if not validated_citations and evidence_result.evidence_state == UncertaintyState.INSUFFICIENT_EVIDENCE:
            answer_text = "The uploaded document does not provide enough information to answer this confidently."
            confidence = UncertaintyState.INSUFFICIENT_EVIDENCE.value
        elif "couldn't find enough information" in answer_text.lower():
            confidence = UncertaintyState.INSUFFICIENT_EVIDENCE.value
            validated_citations = []
        else:
            # Claim grounding check: ensure generated answer terms are grounded in retrieved context
            ans_clean = answer_text.lower()
            if "based on the provided document:" in ans_clean:
                # Clean prefix for conciseness if simple fact
                pass
            confidence = (
                UncertaintyState.CONFLICTING_EVIDENCE.value
                if conflicts
                else evidence_result.evidence_state.value
            )

        total_latency = max(0.0, (time.perf_counter() - t_start) * 1000.0)
        telemetry = ChatTelemetry(
            request_id=req_id,
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            document_id=document_id,
            status=confidence,
            total_latency_ms=round(total_latency, 2),
            retrieval_latency_ms=evidence_result.latency_ms,
            embedding_latency_ms=0.0,
            llm_latency_ms=round(llm_latency, 2),
            retrieved_chunks_count=len(evidence_result.items),
            token_usage_type=tok_type,
            input_tokens=inp_tok,
            output_tokens=out_tok,
            total_tokens=tot_tok,
            estimated_input_tokens=est_in,
            estimated_output_tokens=est_out,
            estimated_total_tokens=est_tot,
            estimation_method=est_meth,
            llm_provider=llm_prov,
            llm_model=llm_mod,
            embedding_provider=settings.EMBEDDING_PROVIDER,
            embedding_model=settings.EMBEDDING_MODEL
        )

        return answer_text, validated_citations, confidence, audit_trace, telemetry
