from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.core.config import settings
from app.core.logging import logger
from app.services.pdf_service import PDFService
from app.services.chunking_service import ChunkingService
from app.services.embedding_service import EmbeddingService
from app.services.vector_store import VectorStore
from app.services.retrieval_service import RetrievalService
from app.services.llm_service import LLMService
from app.services.citation_service import CitationService
from app.services.document_service import DocumentService
from app.services.conversation_service import ConversationService
from app.persistence.database import DatabaseManager
from app.persistence.repository import ConversationRepository
from app.services.intent_router import IntentRouter
from app.services.tools.metadata_tool import DocumentMetadataTool
from app.services.tools.profile_tool import DocumentProfileTool
from app.services.tools.evidence_tool import EvidenceRetrievalTool
from app.services.agent_orchestrator import AgentOrchestrator

from app.api.routes_health import router as health_router
from app.api.routes_documents import router as documents_router
from app.api.routes_chat import router as chat_router
from app.api.routes_conversations import router as conversations_router

app_state = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: initialize services
    logger.info("Initializing Legal Document QA Assistant services...")
    pdf_service = PDFService(max_pages=settings.MAX_DOCUMENT_PAGES)
    chunking_service = ChunkingService(
        chunk_size=settings.CHUNK_SIZE,
        chunk_overlap=settings.CHUNK_OVERLAP,
        min_chunk_size=settings.MIN_CHUNK_SIZE
    )
    embedding_service = EmbeddingService()
    vector_store = VectorStore(storage_dir=settings.VECTOR_STORE_DIR)
    retrieval_service = RetrievalService(embedding_service, vector_store)
    llm_service = LLMService()
    citation_service = CitationService()

    document_service = DocumentService(
        pdf_service=pdf_service,
        chunking_service=chunking_service,
        embedding_service=embedding_service,
        vector_store=vector_store
    )

    db_manager = app_state.get("db_manager") or DatabaseManager(db_path=settings.DATABASE_PATH)
    conversation_repo = app_state.get("conversation_repo") or ConversationRepository(session_factory=db_manager.session_factory)
    conversation_service = app_state.get("conversation_service") or ConversationService(repository=conversation_repo)

    from app.services.tools.structure_tool import SectionStructureTool
    from app.services.tools.reference_tools import CrossReferenceTool, DefinitionTool
    from app.services.tools.comparison_tool import MultiDocumentComparisonTool
    from app.services.legal_reasoning import (
        ConflictDetector,
        TemporalReasoner,
        ObligationExtractor,
        RiskAnalyzer
    )

    intent_router = IntentRouter()
    metadata_tool = DocumentMetadataTool(document_service=document_service)
    profile_tool = DocumentProfileTool(document_service=document_service, repository=conversation_repo)
    evidence_tool = EvidenceRetrievalTool(retrieval_service=retrieval_service)
    structure_tool = SectionStructureTool(document_service=document_service)
    cross_ref_tool = CrossReferenceTool(document_service=document_service)
    definition_tool = DefinitionTool(document_service=document_service)
    comparison_tool = MultiDocumentComparisonTool(document_service=document_service, evidence_tool=evidence_tool)
    conflict_detector = ConflictDetector()
    temporal_reasoner = TemporalReasoner()
    obligation_extractor = ObligationExtractor()
    risk_analyzer = RiskAnalyzer()

    agent_orchestrator = AgentOrchestrator(
        intent_router=intent_router,
        metadata_tool=metadata_tool,
        profile_tool=profile_tool,
        evidence_tool=evidence_tool,
        llm_service=llm_service,
        citation_service=citation_service,
        structure_tool=structure_tool,
        cross_ref_tool=cross_ref_tool,
        definition_tool=definition_tool,
        comparison_tool=comparison_tool,
        conflict_detector=conflict_detector,
        temporal_reasoner=temporal_reasoner,
        obligation_extractor=obligation_extractor,
        risk_analyzer=risk_analyzer
    )

    # Sync vocabulary provider with any pre-loaded vector store chunks across restarts
    if hasattr(embedding_service.provider, "fit_document"):
        for doc_id, doc_chunks in vector_store.chunks_by_doc.items():
            if doc_chunks:
                embedding_service.provider.fit_document(doc_id, [c.text for c in doc_chunks])
    elif hasattr(embedding_service.provider, "fit_corpus") and not getattr(embedding_service.provider, "is_fitted", False):
        for doc_chunks in vector_store.chunks_by_doc.values():
            if doc_chunks:
                embedding_service.provider.fit_corpus([c.text for c in doc_chunks])

    app_state["pdf_service"] = pdf_service
    app_state["chunking_service"] = chunking_service
    app_state["embedding_service"] = embedding_service
    app_state["vector_store"] = vector_store
    app_state["retrieval_service"] = retrieval_service
    app_state["llm_service"] = llm_service
    app_state["citation_service"] = citation_service
    app_state["document_service"] = document_service
    app_state["db_manager"] = db_manager
    app_state["conversation_repo"] = conversation_repo
    app_state["conversation_service"] = conversation_service
    app_state["intent_router"] = intent_router
    app_state["metadata_tool"] = metadata_tool
    app_state["profile_tool"] = profile_tool
    app_state["evidence_tool"] = evidence_tool
    app_state["structure_tool"] = structure_tool
    app_state["cross_ref_tool"] = cross_ref_tool
    app_state["definition_tool"] = definition_tool
    app_state["comparison_tool"] = comparison_tool
    app_state["conflict_detector"] = conflict_detector
    app_state["temporal_reasoner"] = temporal_reasoner
    app_state["obligation_extractor"] = obligation_extractor
    app_state["risk_analyzer"] = risk_analyzer
    app_state["agent_orchestrator"] = agent_orchestrator

    logger.info("Services initialized successfully.")
    yield
    # Shutdown
    logger.info("Shutting down application...")


app = FastAPI(
    title=settings.APP_NAME,
    description="Production-grade Legal Document Q&A with Strict Grounding and Citations",
    version="1.0.0",
    lifespan=lifespan
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API Routers
app.include_router(health_router, prefix="/api")
app.include_router(documents_router, prefix="/api")
app.include_router(chat_router, prefix="/api")
app.include_router(conversations_router, prefix="/api")

# Static frontend files
frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
if frontend_dir.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_dir / "static")), name="static")

    @app.get("/favicon.ico", include_in_schema=False)
    async def serve_favicon():
        return FileResponse(
            str(frontend_dir / "static" / "favicon.svg"),
            media_type="image/svg+xml"
        )

    @app.get("/")
    async def serve_index():
        return FileResponse(str(frontend_dir / "index.html"))
