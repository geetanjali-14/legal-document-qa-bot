from typing import Optional, Dict, Any
from app.core.config import settings
from app.core.logging import logger
from app.providers.interfaces import RAGProvider, LLMProvider
from app.providers.rag_local import LocalRAGProvider
from app.providers.rag_xai import XAIRAGProvider
from app.providers.llm_adapters import (
    GeminiLLMProvider,
    OpenAILLMProvider,
    GroqLLMProvider,
    XAILLMProvider,
    MockLLMProviderAdapter
)


class ProviderFactory:
    """
    Centralized provider factory and registry.
    Ensures provider selection occurs in one place without scattered conditional checks.
    """

    @staticmethod
    def get_rag_provider(
        rag_provider_name: Optional[str] = None,
        retrieval_service: Optional[Any] = None,
        vector_store: Optional[Any] = None,
        **kwargs
    ) -> RAGProvider:
        provider = (rag_provider_name or getattr(settings, "RAG_PROVIDER", "local")).lower()
        logger.info(f"[ProviderFactory] Selecting RAG provider: {provider}")

        if provider == "local":
            if retrieval_service is None or vector_store is None:
                # Lazy import to avoid circular dependency
                from app.main import app_state
                from app.services.retrieval_service import RetrievalService
                from app.services.vector_store import VectorStore
                from app.services.embedding_service import EmbeddingService

                ret_s = retrieval_service or app_state.get("retrieval_service")
                vs = vector_store or app_state.get("vector_store")
                if not vs:
                    vs = VectorStore(storage_dir=settings.VECTOR_STORE_DIR)
                if not ret_s:
                    emb_s = app_state.get("embedding_service") or EmbeddingService()
                    ret_s = RetrievalService(emb_s, vs)
                return LocalRAGProvider(retrieval_service=ret_s, vector_store=vs)

            return LocalRAGProvider(
                retrieval_service=retrieval_service,
                vector_store=vector_store,
                embedding_service=kwargs.get("embedding_service")
            )

        elif provider in ("xai", "grok"):
            return XAIRAGProvider(
                api_key=kwargs.get("api_key"),
                base_url=kwargs.get("base_url"),
                collection_id=kwargs.get("collection_id"),
                client=kwargs.get("client")
            )

        else:
            raise ValueError(f"Unsupported RAG provider: '{provider}'. Valid options: 'local', 'xai'.")

    @staticmethod
    def get_llm_provider(
        llm_provider_name: Optional[str] = None,
        **kwargs
    ) -> LLMProvider:
        provider = (llm_provider_name or settings.LLM_PROVIDER).lower()
        logger.info(f"[ProviderFactory] Selecting LLM provider: {provider}")

        if provider == "gemini":
            return GeminiLLMProvider(
                api_key=kwargs.get("api_key") or settings.LLM_API_KEY,
                model=kwargs.get("model") or settings.LLM_MODEL
            )
        elif provider == "openai":
            return OpenAILLMProvider(
                api_key=kwargs.get("api_key") or settings.LLM_API_KEY,
                model=kwargs.get("model") or settings.LLM_MODEL,
                base_url=kwargs.get("base_url") or settings.LLM_BASE_URL
            )
        elif provider == "groq":
            return GroqLLMProvider(
                api_key=kwargs.get("api_key") or settings.LLM_API_KEY,
                model=kwargs.get("model") or settings.LLM_MODEL,
                base_url=kwargs.get("base_url") or settings.LLM_BASE_URL
            )
        elif provider in ("xai", "grok"):
            return XAILLMProvider(
                api_key=kwargs.get("api_key"),
                model=kwargs.get("model"),
                base_url=kwargs.get("base_url")
            )
        elif provider == "mock":
            return MockLLMProviderAdapter()
        else:
            logger.warning(f"Unknown or fallback LLM provider: '{provider}'. Falling back to MockLLMProviderAdapter.")
            return MockLLMProviderAdapter()


def get_rag_provider(**kwargs) -> RAGProvider:
    return ProviderFactory.get_rag_provider(**kwargs)


def get_llm_provider(**kwargs) -> LLMProvider:
    return ProviderFactory.get_llm_provider(**kwargs)

