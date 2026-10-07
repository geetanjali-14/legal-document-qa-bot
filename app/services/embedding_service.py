from abc import ABC, abstractmethod
from typing import List
import numpy as np
import httpx
from sklearn.feature_extraction.text import TfidfVectorizer
from app.core.config import settings
from app.core.logging import logger


class BaseEmbeddingProvider(ABC):
    @abstractmethod
    def embed_texts(self, texts: List[str]) -> np.ndarray:
        """Embed a list of text strings into an NxDim 2D numpy array."""
        pass

    @abstractmethod
    def embed_query(self, query: str) -> np.ndarray:
        """Embed a single query string into a 1xDim 2D numpy array."""
        pass


class MockEmbeddingProvider(BaseEmbeddingProvider):
    """Deterministic hash-based embedding for zero-dependency testing."""
    def __init__(self, dimension: int = 128):
        self.dimension = dimension

    def _hash_vector(self, text: str) -> np.ndarray:
        vec = np.zeros(self.dimension, dtype=np.float32)
        words = text.lower().split()
        if not words:
            return vec
        for word in words:
            idx = abs(hash(word)) % self.dimension
            vec[idx] += 1.0
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec

    def embed_texts(self, texts: List[str]) -> np.ndarray:
        matrix = [self._hash_vector(t) for t in texts]
        return np.array(matrix, dtype=np.float32)

    def embed_query(self, query: str) -> np.ndarray:
        return np.array([self._hash_vector(query)], dtype=np.float32)


class TFIDFEmbeddingProvider(BaseEmbeddingProvider):
    """
    High-quality local vocabulary-grounded embedding provider using scikit-learn TF-IDF.
    Provides real semantic token overlap and document weighting without external API keys.
    """
    def __init__(self, max_features: int = 1024):
        self.max_features = max_features
        self.vectorizer = TfidfVectorizer(
            max_features=max_features,
            stop_words="english",
            token_pattern=r'(?u)\b\w+\b'
        )
        self.is_fitted = False
        self.corpus_history: List[str] = []

    def fit_corpus(self, texts: List[str]) -> None:
        self.corpus_history.extend(texts)
        self.vectorizer.fit(self.corpus_history)
        self.is_fitted = True

    def embed_texts(self, texts: List[str]) -> np.ndarray:
        if not self.is_fitted:
            self.fit_corpus(texts)
        else:
            # Re-fit or update if new vocabulary appears
            self.fit_corpus(texts)
        sparse_matrix = self.vectorizer.transform(texts)
        return sparse_matrix.toarray().astype(np.float32)

    def embed_query(self, query: str) -> np.ndarray:
        if not self.is_fitted:
            # Emergency fit with query if nothing indexed yet
            self.vectorizer.fit([query])
            self.is_fitted = True
        sparse_vec = self.vectorizer.transform([query])
        return sparse_vec.toarray().astype(np.float32)


class OpenAIEmbeddingProvider(BaseEmbeddingProvider):
    """OpenAI API embedding provider (e.g. text-embedding-3-small)."""
    def __init__(self, api_key: str, model: str = "text-embedding-3-small", base_url: str = ""):
        self.api_key = api_key
        self.model = model
        self.base_url = (base_url or "https://api.openai.com/v1").rstrip("/") + "/embeddings"

    def embed_texts(self, texts: List[str]) -> np.ndarray:
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
            data = resp.json()["data"]
            embeddings = [item["embedding"] for item in data]
            return np.array(embeddings, dtype=np.float32)

    def embed_query(self, query: str) -> np.ndarray:
        return self.embed_texts([query])


class EmbeddingService:
    def __init__(self):
        self.provider = self._resolve_provider()

    def _resolve_provider(self) -> BaseEmbeddingProvider:
        provider_name = settings.EMBEDDING_PROVIDER.lower()
        logger.info(f"Initializing embedding provider: {provider_name}")

        if provider_name == "openai":
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

    def embed_texts(self, texts: List[str]) -> np.ndarray:
        return self.provider.embed_texts(texts)

    def embed_query(self, query: str) -> np.ndarray:
        return self.provider.embed_query(query)
