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

from app.api.routes_health import router as health_router
from app.api.routes_documents import router as documents_router
from app.api.routes_chat import router as chat_router

app_state = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: initialize services
    logger.info("Initializing Legal Document QA Assistant services...")
    pdf_service = PDFService()
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

    app_state["pdf_service"] = pdf_service
    app_state["chunking_service"] = chunking_service
    app_state["embedding_service"] = embedding_service
    app_state["vector_store"] = vector_store
    app_state["retrieval_service"] = retrieval_service
    app_state["llm_service"] = llm_service
    app_state["citation_service"] = citation_service
    app_state["document_service"] = document_service

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

# Static frontend files
frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
if frontend_dir.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_dir / "static")), name="static")

    @app.get("/")
    async def serve_index():
        return FileResponse(str(frontend_dir / "index.html"))
