import pytest
from app.core.config import settings
from app.providers.factory import ProviderFactory, get_rag_provider, get_llm_provider
from app.providers.rag_local import LocalRAGProvider
from app.providers.rag_xai import XAIRAGProvider
from app.providers.llm_adapters import GeminiLLMProvider, XAILLMProvider, MockLLMProviderAdapter
from app.providers.interfaces import RAGProvider, LLMProvider
from app.providers.base import RetrievedChunk, LLMResponse
from app.services.vector_store import VectorStore
from app.services.retrieval_service import RetrievalService
from app.services.embedding_service import EmbeddingService


def test_provider_selection_local(tmp_path):
    """
    RAG_PROVIDER=local selects LocalRAGProvider without requiring xAI credentials or calls.
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


def test_provider_selection_xai_with_credentials():
    """
    RAG_PROVIDER=xai selects XAIRAGProvider without making live paid API calls.
    """
    class MockXAIClient:
        def retrieve(self, document_id, query, top_k):
            return [
                RetrievedChunk(
                    document_id=document_id,
                    chunk_id="chk_xai_1",
                    text="Mock xAI chunk text",
                    score=0.92,
                    page_number=1,
                    section="MockSection"
                )
            ]

    mock_client = MockXAIClient()
    provider = ProviderFactory.get_rag_provider(
        rag_provider_name="xai",
        api_key="xai-test-key-mock",
        client=mock_client
    )

    assert isinstance(provider, XAIRAGProvider)
    assert isinstance(provider, RAGProvider)
    assert provider.provider_name == "xai"

    results = provider.retrieve("doc_123", "test query", top_k=2)
    assert len(results) == 1
    assert isinstance(results[0], RetrievedChunk)
    assert results[0].chunk_id == "chk_xai_1"
    assert results[0].score == 0.92


def test_xai_missing_credentials_raises_clean_error(monkeypatch):
    """
    When RAG_PROVIDER=xai and credentials are missing, produce a clear configuration error.
    Does NOT silently fall back to local RAG.
    """
    monkeypatch.setattr(settings, "XAI_API_KEY", "")
    monkeypatch.setattr(settings, "LLM_API_KEY", "")

    with pytest.raises(ValueError) as excinfo:
        ProviderFactory.get_rag_provider(
            rag_provider_name="xai",
            api_key=""
        )
    assert "xAI credentials are missing" in str(excinfo.value)


def test_local_mode_works_when_xai_credentials_absent(tmp_path, monkeypatch):
    """
    Local mode must start and function properly even when no xAI credentials exist.
    """
    monkeypatch.setattr(settings, "XAI_API_KEY", "")

    vs = VectorStore(storage_dir=tmp_path / "vector_store")
    emb = EmbeddingService()
    ret = RetrievalService(emb, vs)

    provider = ProviderFactory.get_rag_provider(
        rag_provider_name="local",
        retrieval_service=ret,
        vector_store=vs
    )

    assert isinstance(provider, LocalRAGProvider)


def test_llm_provider_selection_gemini(monkeypatch):
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

