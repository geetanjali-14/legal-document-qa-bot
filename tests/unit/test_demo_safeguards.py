import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.core.config import settings
from app.core.security import rate_limiter, sign_session_id


@pytest.fixture(autouse=True)
def reset_limiter_and_settings():
    rate_limiter.reset()
    orig_demo = settings.DEMO_MODE
    yield
    settings.DEMO_MODE = orig_demo
    rate_limiter.reset()


def test_demo_mode_blocks_uploads():
    settings.DEMO_MODE = True
    with TestClient(app) as client:
        # Legacy endpoint upload
        res = client.post(
            "/api/documents/upload",
            files={"file": ("test.pdf", b"%PDF-1.4 dummy", "application/pdf")}
        )
        assert res.status_code == 403
        assert "disabled in public demo mode" in res.json().get("detail", "")

        # v1 endpoint upload
        v1_res = client.post(
            "/api/v1/documents",
            files={"file": ("test.pdf", b"%PDF-1.4 dummy", "application/pdf")}
        )
        assert v1_res.status_code == 403
        assert v1_res.json()["error"]["code"] == "DEMO_MODE_RESTRICTION"


def test_demo_mode_blocks_document_deletion():
    settings.DEMO_MODE = True
    with TestClient(app) as client:
        res = client.delete("/api/documents/doc_demo_sample")
        assert res.status_code == 403

        v1_res = client.delete("/api/v1/documents/doc_demo_sample")
        assert v1_res.status_code == 403


def test_demo_mode_session_isolation_and_conversations():
    settings.DEMO_MODE = True
    with TestClient(app) as client_a:
        # User A creates a conversation and adds a message
        res_a = client_a.post("/api/conversations", json={"title": "Client A Secret Matter"})
        assert res_a.status_code == 201
        conv_a_id = res_a.json()["data"]["conversation_id"]

        from app.main import app_state
        app_state["conversation_service"].add_message(conv_a_id, role="user", content="Hello secret consultation")

        # Verify session cookie was set for Client A
        assert "legal_qa_session" in client_a.cookies

        # User B with different/fresh cookies
        with TestClient(app) as client_b:
            # User B lists conversations: must NOT see User A's conversation
            res_b_list = client_b.get("/api/conversations")
            assert res_b_list.status_code == 200
            b_conv_ids = [c["conversation_id"] for c in res_b_list.json()["data"]]
            assert conv_a_id not in b_conv_ids

            # User B attempts to access User A's conversation directly: rejected with 404
            res_b_get = client_b.get(f"/api/conversations/{conv_a_id}")
            assert res_b_get.status_code == 404

            # User B attempts to delete User A's conversation: rejected with 404
            res_b_del = client_b.delete(f"/api/conversations/{conv_a_id}?document_id=none")
            assert res_b_del.status_code == 404

        # User A CAN access their own conversation
        res_a_get = client_a.get(f"/api/conversations/{conv_a_id}")
        assert res_a_get.status_code == 200
        assert res_a_get.json()["data"]["conversation_id"] == conv_a_id


def test_rate_limiting_enforcement_on_chat():
    settings.DEMO_MODE = True
    rate_limiter.reset()
    client = TestClient(app)

    # Test rate limiter directly on endpoint
    for i in range(settings.RATE_LIMIT_CHAT_PER_MINUTE):
        allowed, _ = rate_limiter.is_allowed("test-rate-key", max_requests=settings.RATE_LIMIT_CHAT_PER_MINUTE, window_seconds=60)
        assert allowed is True

    # Next attempt must be blocked
    allowed, retry_after = rate_limiter.is_allowed("test-rate-key", max_requests=settings.RATE_LIMIT_CHAT_PER_MINUTE, window_seconds=60)
    assert allowed is False
    assert retry_after > 0


def test_session_cookie_signature_tamper_protection():
    secret = settings.SESSION_SECRET
    tampered_cookie = "sess_fake_user.invalid_signature_hex"
    from app.core.security import verify_session_cookie
    verified = verify_session_cookie(tampered_cookie, secret)
    assert verified is None

    valid_signed = sign_session_id("sess_real_user", secret)
    verified_valid = verify_session_cookie(valid_signed, secret)
    assert verified_valid == "sess_real_user"
