from abc import ABC, abstractmethod
from typing import List, Optional
import time
import numpy as np
import httpx
from sklearn.feature_extraction.text import TfidfVectorizer
from app.core.config import settings
from app.core.logging import logger


class BaseEmbeddingProvider(ABC):
    @abstractmethod
    def embed_texts(self, texts: List[str], document_id: Optional[str] = None) -> np.ndarray:
        """Embed a list of text strings into an NxDim 2D numpy array."""
        pass

    @abstractmethod
    def embed_query(self, query: str, document_id: Optional[str] = None) -> np.ndarray:
        """Embed a single query string into a 1xDim 2D numpy array."""
        pass


class MockEmbeddingProvider(BaseEmbeddingProvider):
    """Deterministic hash-based embedding for zero-dependency testing."""
    def __init__(self, dimension: int = 128):
        self.provider_name = "mock"
        self.model_name = "mock-hash"
        self.dimension = dimension

    def _hash_vector(self, text: str) -> np.ndarray:
        vec = np.zeros(self.dimension, dtype=np.float32)
        import re
        cleaned = re.sub(r'[^\w\s]', ' ', text.lower())
        words = [w for w in cleaned.split() if w]
        if not words:
            return vec
        for word in words:
            idx = abs(hash(word)) % self.dimension
            vec[idx] += 1.0
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec

    def embed_texts(self, texts: List[str], document_id: Optional[str] = None) -> np.ndarray:
        matrix = [self._hash_vector(t) for t in texts]
        return np.array(matrix, dtype=np.float32)

    def embed_query(self, query: str, document_id: Optional[str] = None) -> np.ndarray:
        return np.array([self._hash_vector(query)], dtype=np.float32)


class TFIDFEmbeddingProvider(BaseEmbeddingProvider):
    """
    High-quality local vocabulary-grounded embedding provider using scikit-learn TF-IDF.
    Provides document-scoped vectorizers to prevent cross-document vocabulary contamination
    and ensure query vector dimensions always match stored document vector dimensions.
    """
    def __init__(self, max_features: int = 1024):
        self.provider_name = "tfidf"
        self.model_name = "tfidf-scikit"
        self.max_features = max_features
        self.global_vectorizer = self._create_vectorizer()
        self.is_fitted = False
        self.corpus_history: List[str] = []
        # Document-specific vectorizers: document_id -> TfidfVectorizer
        self.doc_vectorizers: dict = {}

    def _create_vectorizer(self) -> TfidfVectorizer:
        return TfidfVectorizer(
            max_features=self.max_features,
            stop_words="english",
            token_pattern=r'(?u)\b\w+\b'
        )

    def fit_document(self, document_id: str, texts: List[str]) -> None:
        """Fit a dedicated vocabulary vectorizer for a specific document."""
        if not texts:
            return
        vec = self._create_vectorizer()
        vec.fit(texts)
        self.doc_vectorizers[document_id] = vec
        logger.info(f"Fitted TF-IDF vectorizer for document {document_id} (vocab_size={len(vec.vocabulary_)})")

    def remove_document(self, document_id: str) -> None:
        """Remove document-scoped vectorizer when document is deleted."""
        self.doc_vectorizers.pop(document_id, None)

    def fit_corpus(self, texts: List[str]) -> None:
        self.corpus_history.extend(texts)
        self.global_vectorizer.fit(self.corpus_history)
        self.is_fitted = True

    def embed_texts(self, texts: List[str], document_id: Optional[str] = None) -> np.ndarray:
        if document_id:
            vec = self._create_vectorizer()
            vec.fit(texts)
            self.doc_vectorizers[document_id] = vec
            sparse_matrix = vec.transform(texts)
            return sparse_matrix.toarray().astype(np.float32)

        if not self.is_fitted:
            self.fit_corpus(texts)
        else:
            self.fit_corpus(texts)
        sparse_matrix = self.global_vectorizer.transform(texts)
        return sparse_matrix.toarray().astype(np.float32)

    def embed_query(self, query: str, document_id: Optional[str] = None) -> np.ndarray:
        if document_id and document_id in self.doc_vectorizers:
            vec = self.doc_vectorizers[document_id]
            sparse_vec = vec.transform([query])
            return sparse_vec.toarray().astype(np.float32)

        if not self.is_fitted:
            self.global_vectorizer.fit([query])
            self.is_fitted = True
        sparse_vec = self.global_vectorizer.transform([query])
        return sparse_vec.toarray().astype(np.float32)


class FastEmbedProvider(BaseEmbeddingProvider):
    """
    Local dense embedding provider using FastEmbed (ONNX Runtime).
    Default model: BAAI/bge-small-en-v1.5 (384-dimensional dense vectors).
    Provides high-speed CPU inference and semantic synonym matching.
    """
    DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"

    def __init__(self, model_name: Optional[str] = None):
        try:
            from fastembed import TextEmbedding
        except ImportError as exc:
            raise ImportError(
                "fastembed is required for FastEmbedProvider. Install it with `pip install fastembed`."
            ) from exc

        self.provider_name = "fastembed"
        self.model_name = model_name or self.DEFAULT_MODEL
        logger.info(f"Loading FastEmbed model: {self.model_name}")
        self._model = TextEmbedding(model_name=self.model_name)
        self.last_tokens: Optional[int] = None

    def embed_texts(self, texts: List[str], document_id: Optional[str] = None) -> np.ndarray:
        if not texts:
            return np.empty((0, 384), dtype=np.float32)
        embeddings = list(self._model.embed(texts))
        return np.array(embeddings, dtype=np.float32)

    def embed_query(self, query: str, document_id: Optional[str] = None) -> np.ndarray:
        embeddings = list(self._model.embed([query]))
        return np.array(embeddings, dtype=np.float32)


class OpenAIEmbeddingProvider(BaseEmbeddingProvider):
    """OpenAI API embedding provider (e.g. text-embedding-3-small)."""
    def __init__(self, api_key: str, model: str = "text-embedding-3-small", base_url: str = ""):
        self.provider_name = "openai"
        self.api_key = api_key
        self.model = model
        self.model_name = model
        self.base_url = (base_url or "https://api.openai.com/v1").rstrip("/") + "/embeddings"
        self.last_tokens: Optional[int] = None

    def embed_texts(self, texts: List[str], document_id: Optional[str] = None) -> np.ndarray:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "input": texts,
            "model": self.model
        }
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(self.base_url, json=payload, headers=headers)
            resp.raise_for_status()
            res_json = resp.json()
            data = res_json["data"]
            usage = res_json.get("usage", {})
            self.last_tokens = usage.get("prompt_tokens") or usage.get("total_tokens")
            embeddings = [item["embedding"] for item in data]
            return np.array(embeddings, dtype=np.float32)

    def embed_query(self, query: str, document_id: Optional[str] = None) -> np.ndarray:
        return self.embed_texts([query], document_id=document_id)


class GeminiEmbeddingProvider(BaseEmbeddingProvider):
    """
    Google Gemini Embedding Provider using official google-genai SDK.
    Default model: text-embedding-004 (768 dimensions).
    """
    DEFAULT_MODEL = "gemini-embedding-2"

    def __init__(self, api_key: str, model: str = "gemini-embedding-2"):
        if not api_key:
            raise ValueError("Gemini API key is required for GeminiEmbeddingProvider.")
        self.provider_name = "gemini"
        self.api_key = api_key
        self.model = model or self.DEFAULT_MODEL
        self.model_name = self.model
        from google.genai import Client
        self._client = Client(api_key=self.api_key)
        self.last_tokens: Optional[int] = None

    def embed_texts(self, texts: List[str], document_id: Optional[str] = None) -> np.ndarray:
        if not texts:
            return np.empty((0, 3072), dtype=np.float32)
        try:
            embeddings = []
            for t in texts:
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        response = self._client.models.embed_content(
                            model=self.model,
                            contents=t
                        )
                        embeddings.append(response.embeddings[0].values)
                        break
                    except Exception as embed_err:
                        err_text = str(embed_err)
                        if ("RESOURCE_EXHAUSTED" in err_text or "Quota exceeded" in err_text):
                            raise
                        if "429" in err_text and attempt < max_retries - 1:
                            backoff = 2.0 * (attempt + 1)
                            logger.warning(f"Embedding rate limit, sleeping {backoff}s...")
                            time.sleep(backoff)
                            continue
                        raise
            return np.array(embeddings, dtype=np.float32)
        except Exception as e:
            err_str = str(e)
            if "RESOURCE_EXHAUSTED" in err_str or "Quota exceeded" in err_str or "429" in err_str:
                logger.warning(f"Gemini embedding quota exhausted. Falling back to 3072-dim deterministic embedding: {e}")
                if not hasattr(self, "_fallback_provider"):
                    self._fallback_provider = MockEmbeddingProvider(dimension=3072)
                return self._fallback_provider.embed_texts(texts, document_id=document_id)
            logger.error(f"Gemini embedding generation error: {e}")
            raise RuntimeError(f"Gemini embedding error: {e}") from None

    def embed_query(self, query: str, document_id: Optional[str] = None) -> np.ndarray:
        if hasattr(self, "_fallback_provider"):
            return self._fallback_provider.embed_query(query, document_id=document_id)
        try:
            return self.embed_texts([query], document_id=document_id)
        except Exception as e:
            err_str = str(e)
            if "RESOURCE_EXHAUSTED" in err_str or "Quota exceeded" in err_str or "429" in err_str:
                logger.warning(f"Gemini embedding quota exhausted for query. Falling back to 3072-dim deterministic embedding: {e}")
                if not hasattr(self, "_fallback_provider"):
                    self._fallback_provider = MockEmbeddingProvider(dimension=3072)
                return self._fallback_provider.embed_query(query, document_id=document_id)
            raise

    def fit_document(self, document_id: str, texts: List[str]) -> None:
        if hasattr(self, "_fallback_provider") and hasattr(self._fallback_provider, "fit_document"):
            self._fallback_provider.fit_document(document_id, texts)

    def remove_document(self, document_id: str) -> None:
        if hasattr(self, "_fallback_provider") and hasattr(self._fallback_provider, "remove_document"):
            self._fallback_provider.remove_document(document_id)


class EmbeddingService:
    def __init__(self):
        self.provider = self._resolve_provider()
        self.last_latency_ms: float = 0.0
        self.last_tokens: Optional[int] = None

    @property
    def provider_name(self) -> str:
        return getattr(self.provider, "provider_name", settings.EMBEDDING_PROVIDER.lower())

    @property
    def model_name(self) -> str:
        return getattr(self.provider, "model_name", settings.EMBEDDING_MODEL)

    def _resolve_provider(self) -> BaseEmbeddingProvider:
        provider_name = settings.EMBEDDING_PROVIDER.lower()
        logger.info(f"Initializing embedding provider: {provider_name}")

        if provider_name == "gemini":
            api_key = settings.EMBEDDING_API_KEY or settings.LLM_API_KEY
            if not api_key:
                logger.warning("API key missing for Gemini embeddings. Falling back to TF-IDF.")
                return TFIDFEmbeddingProvider()
            model = settings.EMBEDDING_MODEL if settings.EMBEDDING_MODEL and "gemini" in settings.EMBEDDING_MODEL else GeminiEmbeddingProvider.DEFAULT_MODEL
            return GeminiEmbeddingProvider(api_key=api_key, model=model)
        elif provider_name == "fastembed":
            model = settings.EMBEDDING_MODEL if settings.EMBEDDING_MODEL and settings.EMBEDDING_MODEL != "text-embedding-3-small" else FastEmbedProvider.DEFAULT_MODEL
            return FastEmbedProvider(model_name=model)
        elif provider_name == "openai":
            if not settings.EMBEDDING_API_KEY:
                logger.warning("EMBEDDING_API_KEY missing for OpenAI. Falling back to TF-IDF.")
                return TFIDFEmbeddingProvider()
            return OpenAIEmbeddingProvider(
                api_key=settings.EMBEDDING_API_KEY,
                model=settings.EMBEDDING_MODEL,
                base_url=settings.EMBEDDING_BASE_URL
            )
        elif provider_name == "mock":
            return MockEmbeddingProvider()
        else:
            return TFIDFEmbeddingProvider()

    def embed_texts(self, texts: List[str], document_id: Optional[str] = None) -> np.ndarray:
        t_start = time.perf_counter()
        result = self.provider.embed_texts(texts, document_id=document_id)
        self.last_latency_ms = max(0.0, (time.perf_counter() - t_start) * 1000.0)
        self.last_tokens = getattr(self.provider, "last_tokens", None)
        return result

    def embed_query(self, query: str, document_id: Optional[str] = None) -> np.ndarray:
        t_start = time.perf_counter()
        result = self.provider.embed_query(query, document_id=document_id)
        self.last_latency_ms = max(0.0, (time.perf_counter() - t_start) * 1000.0)
        self.last_tokens = getattr(self.provider, "last_tokens", None)
        return result

