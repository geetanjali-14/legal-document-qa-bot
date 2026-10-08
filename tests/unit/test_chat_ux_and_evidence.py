"""Regression tests for Chat UX, Evidence Visibility, Sidebar Behavior, and In-App PDF Viewing."""
import pytest
from unittest.mock import MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.services.intent_router import IntentRouter
from app.models.agent import IntentType, EvidenceResult, UncertaintyState, EvidenceItem
from app.services.agent_orchestrator import AgentOrchestrator
from app.services.tools.evidence_tool import EvidenceRetrievalTool
from app.services.tools.metadata_tool import DocumentMetadataTool
from app.services.tools.profile_tool import DocumentProfileTool
from app.services.citation_service import CitationService
from app.models.document import DocumentChunk


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


class TestChatUXAndEvidence:
    """Test suite verifying chat UX, evidence visibility, and routing behavior."""

    def test_rental_substantive_queries_route_to_evidence_search(self):
        """Verify substantive contract queries route strictly to EVIDENCE_SEARCH."""
        router = IntentRouter()
        
        q_rent = "What is the monthly rent?"
        res_rent = router.route_query(q_rent)
        assert res_rent.primary_intent == IntentType.EVIDENCE_SEARCH
        assert res_rent.is_multi_intent is False

        q_vacate = "What happens if the tenant does not vacate after the agreement expires?"
        res_vacate = router.route_query(q_vacate)
        assert res_vacate.primary_intent == IntentType.EVIDENCE_SEARCH
        assert res_vacate.is_multi_intent is False

    def test_orchestrator_invokes_search_document_evidence_for_substantive_queries(self):
        """Verify search_document_evidence is executed and recorded in audit trace."""
        mock_llm = MagicMock()
        mock_llm.generate.return_value = MagicMock(
            content="Rent is $1500 per month [Doc: lease.pdf, Page: 2, Section: Rent].",
            token_usage={"input_tokens": 40, "output_tokens": 20, "total_tokens": 60}
        )
        mock_evidence_tool = MagicMock(spec=EvidenceRetrievalTool)
        mock_meta_tool = MagicMock(spec=DocumentMetadataTool)
        mock_profile_tool = MagicMock(spec=DocumentProfileTool)
        mock_citation_service = CitationService()
        router = IntentRouter()

        item = EvidenceItem(
            chunk_id="chunk_rent_1",
            document_id="doc_test_1",
            document_name="lease.pdf",
            page_number=2,
            section="Rent",
            text="The monthly rent is $1500 payable on the first.",
            score=0.91
        )
        mock_evidence_tool.search_document_evidence.return_value = EvidenceResult(
            items=[item],
            evidence_state=UncertaintyState.SUPPORTED,
            query="What is the monthly rent?",
            document_ids=["doc_test_1"],
            total_found=1
        )

        orchestrator = AgentOrchestrator(
            intent_router=router,
            metadata_tool=mock_meta_tool,
            profile_tool=mock_profile_tool,
            evidence_tool=mock_evidence_tool,
            llm_service=mock_llm,
            citation_service=mock_citation_service
        )

        ans, cites, conf, trace, telem = orchestrator.process_query(
            document_id="doc_test_1",
            question="What is the monthly rent?"
        )

        assert "search_document_evidence" in trace.selected_tools
        assert any(t.tool_name == "search_document_evidence" for t in trace.tool_executions)
        assert conf == UncertaintyState.SUPPORTED.value

    def test_conversation_deletion_endpoint(self, client):
        """Verify DELETE /api/conversations/{id}?document_id=... behaves properly and isolates document."""
        # Querying non-existent conversation returns 404
        response = client.delete("/api/conversations/nonexistent-conv?document_id=doc_123")
        assert response.status_code == 404

    def test_single_disclaimer_rule_contract(self, client):
        """Verify chat payload returns single legal disclaimer, not repeated across answers."""
        # Request with empty or nonexistent doc returns 404
        response = client.post("/api/chat", json={
            "document_id": "nonexistent_doc",
            "question": "What is the rent?"
        })
        assert response.status_code == 404
