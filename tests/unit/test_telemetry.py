import json
import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from app.main import app
from app.core.telemetry import (
    ChatTelemetry,
    DocumentProcessingTelemetry,
    ModelPricing,
    PricingRegistry,
    estimate_tokens,
    telemetry_collector
)
from app.services.llm_service import MockLLMProvider, OpenAILLMProvider, LLMResponse


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def uploaded_contract_id(client):
    pdf_path = Path("documents/synthetic_contract.pdf")
    with open(pdf_path, "rb") as f:
        res = client.post(
            "/api/documents/upload",
            files={"file": ("synthetic_contract.pdf", f, "application/pdf")}
        )
    assert res.status_code == 201
    doc_id = res.json()["data"]["document_id"]
    yield doc_id
    client.delete(f"/api/documents/{doc_id}")


# 1. Request ID Tests
def test_request_id_generated_automatically(client, uploaded_contract_id):
    """Every chat request without an explicit request ID receives a unique generated ID."""
    response = client.post(
        "/api/chat",
        json={
            "document_id": uploaded_contract_id,
            "question": "What is the governing law?"
        }
    )
    assert response.status_code == 200
    header_id = response.headers.get("X-Request-ID")
    assert header_id is not None
    assert header_id.startswith("req_")
    
    data = response.json()["data"]
    assert data["request_id"] == header_id
    assert data["telemetry"]["request_id"] == header_id


def test_request_id_propagated_from_client_header(client, uploaded_contract_id):
    """If client sends X-Request-ID header, it is preserved across the lifecycle and response."""
    custom_id = "req_custom_trace_987654"
    response = client.post(
        "/api/chat",
        json={
            "document_id": uploaded_contract_id,
            "question": "What is the termination period?"
        },
        headers={"X-Request-ID": custom_id}
    )
    assert response.status_code == 200
    assert response.headers.get("X-Request-ID") == custom_id
    data = response.json()["data"]
    assert data["request_id"] == custom_id
    assert data["telemetry"]["request_id"] == custom_id


# 2. Latency Measurement Tests
def test_latencies_measured_and_non_negative(client, uploaded_contract_id):
    """Telemetry records non-negative durations for request total, retrieval, embedding, and LLM."""
    response = client.post(
        "/api/chat",
        json={
            "document_id": uploaded_contract_id,
            "question": "What is the termination notice period?"
        }
    )
    assert response.status_code == 200
    telemetry = response.json()["data"]["telemetry"]

    assert telemetry["total_latency_ms"] >= 0.0
    assert telemetry["retrieval_latency_ms"] >= 0.0
    assert telemetry["embedding_latency_ms"] >= 0.0
    assert telemetry["llm_latency_ms"] >= 0.0
    # Request total encapsulates the retrieval and LLM generation phases
    assert telemetry["total_latency_ms"] >= telemetry["retrieval_latency_ms"]
    assert telemetry["total_latency_ms"] >= telemetry["llm_latency_ms"]


def test_latencies_when_llm_skipped_due_to_insufficient_context(client, uploaded_contract_id):
    """When retrieval finds no evidence, LLM call is omitted and llm_latency_ms is null."""
    response = client.post(
        "/api/chat",
        json={
            "document_id": uploaded_contract_id,
            "question": "What is the Martian spaceship launch sequence protocol?"
        }
    )
    assert response.status_code == 200
    telemetry = response.json()["data"]["telemetry"]

    assert telemetry["total_latency_ms"] >= 0.0
    assert telemetry["retrieval_latency_ms"] >= 0.0
    # LLM was not invoked because context was empty/insufficient
    assert telemetry["llm_latency_ms"] is None


# 3. Token Accounting Tests
def test_token_accounting_actual_and_estimated():
    """Verify total_tokens = input_tokens + output_tokens when known, and explicit estimation marking."""
    # Actual provider usage
    actual_response = LLMResponse(
        content="Termination is 30 days.",
        input_tokens=150,
        output_tokens=25,
        total_tokens=175,
        token_usage_type="actual",
        latency_ms=12.5,
        provider="openai",
        model="gpt-4o-mini"
    )
    assert actual_response.total_tokens == actual_response.input_tokens + actual_response.output_tokens
    assert actual_response.token_usage_type == "actual"

    # Mock provider (estimated usage only)
    mock = MockLLMProvider()
    mock_resp = mock.generate_answer(
        question="What is the notice period?",
        context_chunks=["Termination requires thirty days notice."]
    )
    assert isinstance(mock_resp, LLMResponse)
    assert mock_resp.input_tokens is None
    assert mock_resp.output_tokens is None
    assert mock_resp.total_tokens is None
    assert mock_resp.token_usage_type == "estimated"
    assert mock_resp.estimation_method == "char_ratio_4"
    assert mock_resp.estimated_input_tokens > 0
    assert mock_resp.estimated_output_tokens > 0
    assert mock_resp.estimated_total_tokens == mock_resp.estimated_input_tokens + mock_resp.estimated_output_tokens


# 4. Unknown Usage Handling Tests
def test_unknown_usage_does_not_crash():
    """If provider does not expose token usage metadata, system handles it gracefully."""
    llm_resp = LLMResponse(
        content="General legal response.",
        input_tokens=None,
        output_tokens=None,
        total_tokens=None,
        token_usage_type="unknown"
    )
    assert llm_resp.token_usage_type == "unknown"
    assert llm_resp.total_tokens is None

    # Telemetry model validation with unknown tokens
    telem = ChatTelemetry(
        request_id="req_test_unknown",
        total_latency_ms=15.0,
        token_usage_type="unknown",
        input_tokens=None,
        output_tokens=None,
        total_tokens=None,
        estimated_llm_cost=None
    )
    assert telem.input_tokens is None
    assert telem.output_tokens is None
    assert telem.total_tokens is None
    assert telem.estimated_llm_cost is None


# 5. Cost Calculation Tests
def test_cost_calculation_formula_and_registry():
    """Verify cost = tokens / 1_000_000 * price_per_million and centralized configuration."""
    registry = PricingRegistry()
    registry.register(ModelPricing(
        provider="custom_provider",
        model="custom_model",
        input_price_per_million=2.00,
        output_price_per_million=8.00
    ))

    # 1,000,000 in, 1,000,000 out => 2.00 + 8.00 = 10.00
    cost_full = registry.calculate_cost("custom_provider", "custom_model", 1_000_000, 1_000_000)
    assert cost_full == 10.00

    # 500,000 in, 100,000 out => (0.5 * 2) + (0.1 * 8) = 1.00 + 0.80 = 1.80
    cost_partial = registry.calculate_cost("custom_provider", "custom_model", 500_000, 100_000)
    assert cost_partial == 1.80

    # 1,000 in, 500 out => (0.001 * 2) + (0.0005 * 8) = 0.002 + 0.004 = 0.006
    cost_small = registry.calculate_cost("custom_provider", "custom_model", 1000, 500)
    assert cost_small == 0.006

    # gpt-4o-mini default pricing (0.15 in, 0.60 out)
    cost_mini = registry.calculate_cost("openai", "gpt-4o-mini", 1000, 500)
    expected_mini = (1000 / 1_000_000.0) * 0.15 + (500 / 1_000_000.0) * 0.60
    assert cost_mini == round(expected_mini, 8)

    # text-embedding-3-small default pricing (0.02 in, 0.0 out)
    cost_emb = registry.calculate_cost("openai", "text-embedding-3-small", 50_000, 0)
    assert cost_emb == round((50_000 / 1_000_000.0) * 0.02, 8)

    # Unconfigured provider/model returns None (null), never invented pricing
    assert registry.calculate_cost("unknown_provider", "unknown_model", 1000, 500) is None
    assert registry.calculate_cost("mock", "mock-grounded", 1000, 500) is None


# 6. No Secret or Document Content Leakage Tests
def test_no_sensitive_document_or_secret_leakage(client, uploaded_contract_id):
    """Telemetry records must NEVER contain confidential contract text, prompt text, answers, or keys."""
    response = client.post(
        "/api/chat",
        json={
            "document_id": uploaded_contract_id,
            "question": "What is the governing law?"
        }
    )
    assert response.status_code == 200
    telemetry_dict = response.json()["data"]["telemetry"]
    telemetry_json_str = json.dumps(telemetry_dict).lower()

    # Forbidden text inspection
    forbidden_terms = [
        "confidential",
        "delaware",       # Answer string should not be in telemetry
        "governing law",  # Question string should not be in telemetry
        "api_key",
        "secret",
        "authorization",
        "bearer",
        "system_prompt",
        "prompt_content"
    ]
    for term in forbidden_terms:
        assert term not in telemetry_json_str, f"Forbidden term '{term}' leaked into telemetry!"

    # Also verify latest document processing telemetry does not leak document text or secrets
    latest_doc = telemetry_collector.get_latest_document()
    if latest_doc:
        doc_dict = latest_doc.model_dump()
        # Verify no content/text fields exist in DocumentProcessingTelemetry schema
        assert "text" not in doc_dict
        assert "content" not in doc_dict
        assert "chunks" not in doc_dict
        assert "pages" not in doc_dict
        doc_json = json.dumps(doc_dict).lower()
        for term in ["delaware", "30 days", "confidentiality", "indemnification", "secret", "api_key"]:
            assert term not in doc_json, f"Sensitive term '{term}' leaked into document telemetry!"



# 7. Document Processing Telemetry Verification
def test_document_processing_telemetry():
    """Verify document processing measures extraction, chunking, embedding, indexing latencies."""
    doc_telem = DocumentProcessingTelemetry(
        document_id="doc_test123",
        filename="test.pdf",
        file_size_bytes=10240,
        page_count=3,
        chunk_count=12,
        extraction_latency_ms=15.2,
        chunking_latency_ms=4.1,
        embedding_latency_ms=30.0,
        indexing_latency_ms=2.3,
        total_latency_ms=51.6,
        embedding_provider="tfidf",
        embedding_model="default"
    )
    assert doc_telem.total_latency_ms >= 50.0
    assert doc_telem.extraction_latency_ms >= 0.0
    assert doc_telem.chunking_latency_ms >= 0.0
    assert doc_telem.embedding_latency_ms >= 0.0
    assert doc_telem.indexing_latency_ms >= 0.0
    assert doc_telem.file_size_bytes == 10240
    assert doc_telem.chunk_count == 12
