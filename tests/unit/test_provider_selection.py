import pytest
from app.core.config import settings
from app.providers.factory import ProviderFactory, get_rag_provider, get_llm_provider
from app.providers.rag_local import LocalRAGProvider
from app.providers.llm_adapters import GroqLLMProvider, GeminiLLMProvider, MockLLMProviderAdapter
from app.providers.interfaces import RAGProvider, LLMProvider
from app.providers.base import RetrievedChunk, LLMResponse
from app.services.vector_store import VectorStore
from app.services.retrieval_service import RetrievalService
from app.services.embedding_service import EmbeddingService


def test_provider_selection_local(tmp_path):
    """
    RAG_PROVIDER=local selects LocalRAGProvider without requiring external RAG credentials.
    """
    vs = VectorStore(storage_dir=tmp_path / "vector_store")
    emb = EmbeddingService()
    ret = RetrievalService(emb, vs)

    provider = ProviderFactory.get_rag_provider(
        rag_provider_name="local",
        retrieval_service=ret,
        vector_store=vs
    )

    assert isinstance(provider, LocalRAGProvider)
    assert isinstance(provider, RAGProvider)
    assert provider.provider_name == "local"


def test_unsupported_rag_provider_raises_clean_error():
    """
    Unsupported RAG provider names raise clean ValueError.
    """
    with pytest.raises(ValueError) as excinfo:
        ProviderFactory.get_rag_provider(rag_provider_name="unsupported_rag")
    assert "Unsupported RAG provider" in str(excinfo.value)


def test_llm_provider_selection_groq():
    """
    LLM_PROVIDER=groq selects GroqLLMProvider.
    """
    provider = ProviderFactory.get_llm_provider(
        llm_provider_name="groq",
        api_key="test-groq-key"
    )

    assert isinstance(provider, GroqLLMProvider)
    assert isinstance(provider, LLMProvider)
    assert provider.provider_name == "groq"


def test_llm_provider_selection_gemini():
    """
    LLM_PROVIDER=gemini selects GeminiLLMProvider.
    """
    provider = ProviderFactory.get_llm_provider(
        llm_provider_name="gemini",
        api_key="test-gemini-key"
    )

    assert isinstance(provider, GeminiLLMProvider)
    assert isinstance(provider, LLMProvider)
    assert provider.provider_name == "gemini"


def test_llm_provider_selection_mock():
    """
    LLM_PROVIDER=mock selects MockLLMProviderAdapter.
    """
    provider = ProviderFactory.get_llm_provider(
        llm_provider_name="mock"
    )

    assert isinstance(provider, MockLLMProviderAdapter)
    assert isinstance(provider, LLMProvider)
    assert provider.provider_name == "mock"

