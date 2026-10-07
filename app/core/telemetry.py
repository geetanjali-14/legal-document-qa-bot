import json
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from app.core.logging import logger


class ModelPricing(BaseModel):
    """Pricing configuration for a model in USD per 1,000,000 tokens."""
    provider: str
    model: str
    input_price_per_million: float = Field(..., ge=0.0)
    output_price_per_million: float = Field(default=0.0, ge=0.0)


class PricingRegistry:
    """
    Centralized pricing registry for LLM and embedding providers.
    Pricing is configured per million tokens.
    If a provider/model is not registered, cost is reported as null (None).
    """
    def __init__(self):
        self._registry: Dict[str, ModelPricing] = {}
        self._init_defaults()

    def _make_key(self, provider: str, model: str) -> str:
        return f"{provider.strip().lower()}::{model.strip().lower()}"

    def _init_defaults(self):
        # Published standard pricing benchmarks (USD per 1M tokens)
        defaults = [
            ModelPricing(
                provider="openai",
                model="gpt-4o-mini",
                input_price_per_million=0.15,
                output_price_per_million=0.60
            ),
            ModelPricing(
                provider="openai",
                model="gpt-4o",
                input_price_per_million=2.50,
                output_price_per_million=10.00
            ),
            ModelPricing(
                provider="openai",
                model="text-embedding-3-small",
                input_price_per_million=0.02,
                output_price_per_million=0.0
            ),
            ModelPricing(
                provider="openai",
                model="text-embedding-3-large",
                input_price_per_million=0.13,
                output_price_per_million=0.0
            ),
        ]
        for p in defaults:
            self.register(p)

    def register(self, pricing: ModelPricing) -> None:
        key = self._make_key(pricing.provider, pricing.model)
        self._registry[key] = pricing

    def get_pricing(self, provider: str, model: str) -> Optional[ModelPricing]:
        key = self._make_key(provider, model)
        return self._registry.get(key)

    def calculate_cost(
        self,
        provider: str,
        model: str,
        input_tokens: Optional[int],
        output_tokens: Optional[int] = 0
    ) -> Optional[float]:
        """
        Calculates estimated cost based on token counts and configured pricing.
        Returns None if pricing is not configured for the provider/model,
        or if token counts are unavailable.
        Formula: (input_tokens / 1_000_000) * input_price + (output_tokens / 1_000_000) * output_price
        """
        pricing = self.get_pricing(provider, model)
        if pricing is None:
            return None

        if input_tokens is None and output_tokens is None:
            return None

        inp = input_tokens or 0
        out = output_tokens or 0

        input_cost = (inp / 1_000_000.0) * pricing.input_price_per_million
        output_cost = (out / 1_000_000.0) * pricing.output_price_per_million
        total = input_cost + output_cost
        return round(total, 8)


pricing_registry = PricingRegistry()


def estimate_tokens(text: str) -> int:
    """
    Documented heuristic token estimation when provider usage metadata is unavailable.
    Uses English text character ratio approximation (~4 characters per token).
    Never labeled as actual provider billing tokens.
    """
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


class ChatTelemetry(BaseModel):
    """
    Telemetry record for chat / Q&A operations.
    Contains NO raw documents, full prompts, or confidential legal texts.
    """
    event: str = "chat_request_completed"
    request_id: str
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    document_id: Optional[str] = None
    status: str = "success"

    # Latencies in milliseconds (monotonic timer)
    total_latency_ms: float = Field(..., ge=0.0)
    retrieval_latency_ms: Optional[float] = Field(default=None, ge=0.0)
    embedding_latency_ms: Optional[float] = Field(default=None, ge=0.0)
    llm_latency_ms: Optional[float] = Field(default=None, ge=0.0)

    # Retrieval counts
    retrieved_chunks_count: Optional[int] = Field(default=None, ge=0)

    # Token accounting
    token_usage_type: str = "unknown"  # "actual", "estimated", "unknown"
    input_tokens: Optional[int] = Field(default=None, ge=0)
    output_tokens: Optional[int] = Field(default=None, ge=0)
    total_tokens: Optional[int] = Field(default=None, ge=0)

    # Clearly distinguished estimates when provider usage is absent
    estimated_input_tokens: Optional[int] = Field(default=None, ge=0)
    estimated_output_tokens: Optional[int] = Field(default=None, ge=0)
    estimated_total_tokens: Optional[int] = Field(default=None, ge=0)
    estimation_method: Optional[str] = None

    # Model & provider identifiers
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None
    embedding_provider: Optional[str] = None
    embedding_model: Optional[str] = None

    # Estimated costs in USD
    estimated_llm_cost: Optional[float] = None
    estimated_embedding_cost: Optional[float] = None
    estimated_total_cost: Optional[float] = None
    error_category: Optional[str] = None


class DocumentProcessingTelemetry(BaseModel):
    """
    Telemetry record for document ingestion operations.
    Contains NO raw document content or chunk texts.
    """
    event: str = "document_processing_completed"
    document_id: str
    filename: str
    file_size_bytes: int = Field(..., ge=0)
    page_count: int = Field(..., ge=0)
    chunk_count: int = Field(..., ge=0)

    # Phase latencies in milliseconds
    extraction_latency_ms: float = Field(..., ge=0.0)
    chunking_latency_ms: float = Field(..., ge=0.0)
    embedding_latency_ms: float = Field(..., ge=0.0)
    indexing_latency_ms: float = Field(..., ge=0.0)
    total_latency_ms: float = Field(..., ge=0.0)

    embedding_provider: str
    embedding_model: str
    embedding_tokens: Optional[int] = None
    estimated_embedding_cost: Optional[float] = None
    status: str = "success"
    is_duplicate: bool = Field(default=False)
    content_hash: Optional[str] = None
    error_category: Optional[str] = None



class TelemetryCollector:
    """Thread-safe collector for in-memory telemetry records (for verification & testing)."""
    def __init__(self, max_records: int = 100):
        self._max_records = max_records
        self._chat_records: List[ChatTelemetry] = []
        self._doc_records: List[DocumentProcessingTelemetry] = []
        self._lock = threading.Lock()

    def record_chat(self, record: ChatTelemetry) -> None:
        with self._lock:
            self._chat_records.append(record)
            if len(self._chat_records) > self._max_records:
                self._chat_records.pop(0)

    def record_document(self, record: DocumentProcessingTelemetry) -> None:
        with self._lock:
            self._doc_records.append(record)
            if len(self._doc_records) > self._max_records:
                self._doc_records.pop(0)

    def get_latest_chat(self) -> Optional[ChatTelemetry]:
        with self._lock:
            return self._chat_records[-1] if self._chat_records else None

    def get_latest_document(self) -> Optional[DocumentProcessingTelemetry]:
        with self._lock:
            return self._doc_records[-1] if self._doc_records else None

    def get_chat_records(self) -> List[ChatTelemetry]:
        with self._lock:
            return list(self._chat_records)

    def get_doc_records(self) -> List[DocumentProcessingTelemetry]:
        with self._lock:
            return list(self._doc_records)

    def clear(self) -> None:
        with self._lock:
            self._chat_records.clear()
            self._doc_records.clear()


telemetry_collector = TelemetryCollector()


def record_chat_telemetry(record: ChatTelemetry) -> None:
    """Emits structured JSON log and retains record in telemetry collector."""
    telemetry_collector.record_chat(record)
    # Structured machine-readable log without sensitive document contents
    logger.info(f"chat_telemetry: {record.model_dump_json()}")


def record_document_telemetry(record: DocumentProcessingTelemetry) -> None:
    """Emits structured JSON log and retains record in telemetry collector."""
    telemetry_collector.record_document(record)
    logger.info(f"document_telemetry: {record.model_dump_json()}")

