"""Comprehensive Unit and Integration Tests for Phase P2 & P3 Features:
- P2-DOC-01: StructureParser (hierarchy, section IDs, breadcrumbs)
- P2-TOOL-04: SectionStructureTool (deterministic navigation, table of contents)
- P2-TOOL-05: CrossReferenceTool (resolve referenced sections with isolated document scope)
- P2-TOOL-05B: DefinitionTool (defined terms registry)
- P2-MDOC-01: MultiDocumentComparisonTool (isolated comparison, status classifications)
- P3-REAS-01: ConflictDetector (potential contradiction detection)
- P3-TEMPORAL: TemporalReasoner (dates, notice periods, deadlines)
- P3-OBLE-01: ObligationExtractor (modality, party, action)
- P3-RISK: RiskAnalyzer (analytical risk observations)
- P3-RETRIEVAL: Context deduplication
"""
import pytest
from app.models.document import PageContent, DocumentChunk
from app.services.structure_parser import StructureParser
from app.services.tools.structure_tool import SectionStructureTool
from app.services.tools.reference_tools import CrossReferenceTool, DefinitionTool
from app.services.tools.comparison_tool import MultiDocumentComparisonTool
from app.services.legal_reasoning import (
    ConflictDetector,
    TemporalReasoner,
    ObligationExtractor,
    RiskAnalyzer
)
from app.services.retrieval_service import RetrievalService


@pytest.fixture
def sample_agreement_pages():
    p1 = (
        "MASTER SERVICES AGREEMENT\n\n"
        "This Master Services Agreement is entered into by and between Acme Corp and Beta LLC.\n\n"
        "\"Confidential Information\" means all non-public proprietary data disclosed by either party.\n\n"
        "Article 1. Definitions and Interpretation\n"
        "1.1 Defined Terms. As used herein, terms have the meanings set forth below.\n\n"
        "Article 2. Termination\n"
        "2.1 Termination for Cause. Either party may terminate upon thirty (30) days notice.\n"
        "2.2 Termination for Convenience. Subject to Section 4.2, Client may terminate with 60 days notice.\n"
    )
    p2 = (
        "Article 3. Fees and Payment\n"
        "3.1 Invoices. Client shall pay all undisputed invoices within thirty (30) days of receipt.\n"
        "3.2 Late Fees. Overdue amounts bear interest at 1.5% per month.\n\n"
        "Article 4. General Provisions\n"
        "4.1 Governing Law. This Agreement is governed by Delaware law.\n"
        "4.2 Termination Notice. Notice under Section 2.2 must be delivered in writing.\n"
    )
    return [
        PageContent(page_number=1, text=p1, char_count=len(p1)),
        PageContent(page_number=2, text=p2, char_count=len(p2))
    ]


def test_structure_parser_hierarchy_and_breadcrumbs(sample_agreement_pages):
    parser = StructureParser()
    structure = parser.parse_document(
        document_id="doc_test_struct",
        content_hash="hash_12345",
        pages=sample_agreement_pages
    )

    assert structure.document_id == "doc_test_struct"
    assert len(structure.nodes) >= 2  # Articles detected
    assert "2.1" in structure.flat_sections or "terminationforcause" in structure.flat_sections

    # Check breadcrumb presence
    sec_node = structure.flat_sections.get("2.1")
    if sec_node:
        assert sec_node.level in [2, 3]
        assert any("Article" in b for b in sec_node.breadcrumb)


def test_structure_parser_definitions(sample_agreement_pages):
    parser = StructureParser()
    structure = parser.parse_document(
        document_id="doc_test_def",
        content_hash="hash_defs",
        pages=sample_agreement_pages
    )

    assert "confidential information" in structure.definitions
    defn = structure.definitions["confidential information"]
    assert defn.term == "Confidential Information"
    assert "non-public proprietary data" in defn.definition


def test_structure_parser_cross_references(sample_agreement_pages):
    parser = StructureParser()
    structure = parser.parse_document(
        document_id="doc_test_refs",
        content_hash="hash_refs",
        pages=sample_agreement_pages
    )

    assert len(structure.cross_references) >= 1
    targets = [ref.target_ref for ref in structure.cross_references]
    assert any("Section 4.2" in t or "4.2" in t for t in targets)


def test_section_structure_tool(sample_agreement_pages):
    parser = StructureParser()
    structure = parser.parse_document("doc_mock", "hash_mock", sample_agreement_pages)

    class MockDocService:
        def get_document_structure(self, doc_id):
            return structure

    tool = SectionStructureTool(document_service=MockDocService())
    res = tool.get_section_structure("doc_mock", section_query="2.1")

    assert res.document_id == "doc_mock"
    assert res.total_sections > 0
    assert len(res.table_of_contents) > 0


def test_cross_reference_tool(sample_agreement_pages):
    parser = StructureParser()
    structure = parser.parse_document("doc_mock", "hash_mock", sample_agreement_pages)

    class MockDocService:
        def get_document_structure(self, doc_id):
            return structure

    tool = CrossReferenceTool(document_service=MockDocService())
    res = tool.resolve_reference("doc_mock", "Section 4.2")

    assert res["found"] is True
    assert "4.2" in str(res.get("resolved_section_id"))
    assert res["page_start"] == 2


def test_definition_tool(sample_agreement_pages):
    parser = StructureParser()
    structure = parser.parse_document("doc_mock", "hash_mock", sample_agreement_pages)

    class MockDocService:
        def get_document_structure(self, doc_id):
            return structure

    tool = DefinitionTool(document_service=MockDocService())
    res = tool.lookup_definition("doc_mock", "Confidential Information")

    assert res["found"] is True
    assert res["is_defined_term"] is True
    assert "non-public" in res["definition"]

    missing = tool.lookup_definition("doc_mock", "NonExistentTerm")
    assert missing["found"] is False


def test_conflict_detector():
    detector = ConflictDetector()

    class MockChunk:
        def __init__(self, text, section, page):
            self.text = text
            self.section = section
            self.page_number = page

    items = [
        MockChunk("Either party may terminate upon thirty (30) days notice.", "Section 4 Notice", 1),
        MockChunk("Notice of termination requires forty-five (45) days advance written communication.", "Section 11 Termination", 3),
    ]

    conflicts = detector.detect_conflicts(items)
    assert len(conflicts) >= 1
    assert conflicts[0].issue_type == "notice_period"
    assert "Section 4 Notice" in conflicts[0].description
    assert "Section 11 Termination" in conflicts[0].description


def test_temporal_reasoner():
    reasoner = TemporalReasoner()
    text = (
        "Client shall deliver termination notice at least 60 days before expiration. "
        "Vendor shall remedy any breach within 30 days of notice."
    )
    events = reasoner.extract_temporal_events(text, section="Section 8", page=2)

    assert len(events) >= 2
    types = [e.event_type for e in events]
    assert "NOTICE_WINDOW" in types
    assert "DEADLINE" in types or "CURE_PERIOD" in types


def test_obligation_extractor():
    extractor = ObligationExtractor()
    text = (
        "Vendor shall maintain professional liability insurance throughout the term. "
        "Client may not disclose confidential materials without consent."
    )
    obligations = extractor.extract_obligations(text, section="Sec 5", page=1)

    assert len(obligations) >= 2
    types = {o.obligation_type for o in obligations}
    assert "obligation" in types
    assert "prohibition" in types


def test_risk_analyzer():
    analyzer = RiskAnalyzer()

    class MockChunk:
        def __init__(self, text, section, page):
            self.text = text
            self.section = section
            self.page_number = page

    items = [
        MockChunk("Limitation of Liability: In no event shall either party's liability exceed fees paid, except that this limitation shall not apply to indemnification obligations.", "Section 9 Liability", 2),
        MockChunk("Termination: Company may terminate this agreement at its sole discretion without cause.", "Section 12 Termination", 4)
    ]

    risks = analyzer.analyze_risks(items)
    assert len(risks) >= 1
    obs_types = [r.observation_type for r in risks]
    assert "uncapped_liability" in obs_types or "one_sided_termination" in obs_types


def test_retrieval_context_deduplication():
    from unittest.mock import MagicMock
    ret_service = RetrievalService(
        embedding_service=MagicMock(),
        vector_store=MagicMock()
    )

    chunk_a = DocumentChunk(
        chunk_id="c1",
        document_id="d1",
        document_name="Test Doc",
        page_number=1,
        text="The vendor shall provide services according to standard specifications."
    )
    chunk_b = DocumentChunk(
        chunk_id="c2",
        document_id="d1",
        document_name="Test Doc",
        page_number=1,
        text="The vendor shall provide services according to standard specifications."  # Exact duplicate
    )
    chunk_c = DocumentChunk(
        chunk_id="c3",
        document_id="d1",
        document_name="Test Doc",
        page_number=2,
        text="All fees must be settled within 30 days of invoice receipt."
    )

    results = [(chunk_a, 0.9), (chunk_b, 0.85), (chunk_c, 0.7)]
    deduped = ret_service.deduplicate_chunks(results)

    assert len(deduped) == 2
    assert deduped[0][0].chunk_id == "c1"
    assert deduped[1][0].chunk_id == "c3"


def test_cross_reference_annexure_and_schedule():
    """Verify CrossReferenceTool resolves Annexures and Schedules."""
    from unittest.mock import MagicMock
    parser = StructureParser()
    p1 = "1. Deliverables\nDeliverables are set forth in Annexure A.\n\nAnnexure A. Specifications\nServer hardware must have 64GB RAM."
    pages = [PageContent(page_number=1, text=p1, char_count=len(p1))]
    structure = parser.parse_document(document_id="doc_annexure", content_hash="hash_a", pages=pages)

    mock_doc_service = MagicMock()
    mock_doc_service.get_document_structure.return_value = structure

    tool = CrossReferenceTool(document_service=mock_doc_service)

    res = tool.resolve_reference("doc_annexure", "Annexure A")
    assert res["found"] is True
    assert "Specifications" in res["title"] or "Annexure A" in res["title"]
    assert "Specifications" in res["text_content"] or "Annexure A" in res["text_content"]


def test_hierarchical_chunking_parent_child_provenance():
    """Verify hierarchical chunking assigns clause, section, and parent_chunk_id."""
    from app.services.chunking_service import ChunkingService
    chunker = ChunkingService(chunk_size=200, chunk_overlap=20)
    p1 = (
        "Section 15. Termination\n"
        "15.1 Termination by Owner. The Owner may terminate upon 30 days notice.\n"
        "15.2 Termination by Tenant. The Tenant may terminate upon 60 days notice.\n"
    )
    pages = [PageContent(page_number=1, text=p1, char_count=len(p1))]
    chunks = chunker.chunk_document(document_id="doc_hier", document_name="Agreement.pdf", pages=pages)

    assert len(chunks) >= 1
    for c in chunks:
        assert c.document_id == "doc_hier"
        assert c.content_hash != ""
        assert c.token_count > 0
    # At least one chunk has clause number or section number detected
    assert any(c.clause_number or c.section_number for c in chunks)


def test_grok_and_mistral_provider_initialization():
    """Verify Grok and Mistral providers instantiate with custom endpoints."""
    from app.services.llm_service import GrokLLMProvider, MistralLLMProvider
    grok = GrokLLMProvider(api_key="mock-grok-key", model="grok-beta")
    assert grok.provider_name == "grok"
    assert "api.x.ai" in grok.base_url

    mistral = MistralLLMProvider(api_key="mock-mistral-key", model="mistral-large-latest")
    assert mistral.provider_name == "mistral"
    assert "api.mistral.ai" in mistral.base_url


def test_retrieval_candidate_reranking():
    """Verify rerank_candidates boosts chunks matching query clause references."""
    from unittest.mock import MagicMock
    ret_service = RetrievalService(embedding_service=MagicMock(), vector_store=MagicMock())

    chunk1 = DocumentChunk(
        chunk_id="c1",
        document_id="d1",
        document_name="Test Agreement",
        page_number=1,
        section="Section 15 Termination",
        clause_number="15.1",
        text="Either party may terminate on written notice."
    )
    chunk2 = DocumentChunk(
        chunk_id="c2",
        document_id="d1",
        document_name="Test Agreement",
        page_number=2,
        section="Section 3 Fees",
        clause_number="3.1",
        text="Invoices are due within 30 days."
    )

    candidates = [(chunk2, 0.6), (chunk1, 0.5)]
    reranked = ret_service.rerank_candidates("What are the terms in Section 15?", candidates)

    assert len(reranked) == 2
    # chunk1 should be boosted to first place due to "Section 15" match
    assert reranked[0][0].chunk_id == "c1"


