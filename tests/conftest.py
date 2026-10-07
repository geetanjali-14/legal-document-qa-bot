"""
Pytest configuration and global fixtures.
Enforces that standard automated tests default to MockLLMProvider so tests never
make un-mocked external API calls, satisfying STEP 10:
'DO NOT make real Gemini API calls during the normal test suite.'
"""

import os
import pytest
from app.core.config import settings
from app.services.llm_service import MockLLMProvider
from app.main import app_state

@pytest.fixture(autouse=True)
def default_mock_llm(request, monkeypatch):
    """
    Ensures unit and integration tests run deterministically with Mock LLM
    unless a test explicitly marks itself with @pytest.mark.no_mock_llm or LIVE_GEMINI_TEST=1.
    """
    if os.environ.get("LIVE_GEMINI_TEST") == "1" or request.node.get_closest_marker("no_mock_llm"):
        yield
        return

    from app.services.llm_service import LLMService
    monkeypatch.setattr(LLMService, "_resolve_provider", lambda self: MockLLMProvider())

    if "llm_service" in app_state:
        monkeypatch.setattr(app_state["llm_service"], "provider", MockLLMProvider())

    yield
