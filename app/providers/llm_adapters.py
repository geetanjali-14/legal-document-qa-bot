from typing import List, Optional
from app.models.chat import Message
from app.providers.interfaces import LLMProvider
from app.providers.base import LLMResponse
from app.services.llm_service import (
    GeminiLLMProvider as InternalGeminiProvider,
    OpenAILLMProvider as InternalOpenAIProvider,
    GroqLLMProvider as InternalGroqProvider,
    MockLLMProvider as InternalMockProvider
)
from app.core.config import settings
from app.core.logging import logger


class GroqLLMProvider(LLMProvider):
    """
    Wraps existing Groq LLM implementation behind the LLMProvider interface.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None
    ):
        key = api_key or settings.LLM_API_KEY or getattr(settings, "GROQ_API_KEY", "")
        if not key:
            raise ValueError("Groq API key is required for GroqLLMProvider.")
        m = model or (settings.LLM_MODEL if settings.LLM_MODEL and settings.LLM_MODEL != "gpt-4o-mini" else "llama-3.3-70b-versatile")
        b_url = base_url or settings.LLM_BASE_URL or "https://api.groq.com/openai/v1"
        self._provider = InternalGroqProvider(api_key=key, model=m, base_url=b_url)
        self.provider_name = "groq"
        self.model = m

    def generate_answer(
        self,
        question: str,
        context_chunks: List[str],
        history: Optional[List[Message]] = None
    ) -> LLMResponse:
        res = self._provider.generate_answer(question, context_chunks, history)
        if isinstance(res, LLMResponse):
            return res
        return LLMResponse(
            content=str(res),
            provider=self.provider_name,
            model=self.model,
            token_usage_type="unknown"
        )



class GeminiLLMProvider(LLMProvider):
    """
    Wraps existing Gemini LLM implementation behind the LLMProvider interface.
    Preserves exact prompts, token estimation, grounding behavior, and retry mechanisms.
    """

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        key = api_key or settings.LLM_API_KEY
        if not key:
            raise ValueError("Gemini API key is required for GeminiLLMProvider.")
        m = model or settings.LLM_MODEL
        self._provider = InternalGeminiProvider(api_key=key, model=m)
        self.provider_name = "gemini"
        self.model = m

    def generate_answer(
        self,
        question: str,
        context_chunks: List[str],
        history: Optional[List[Message]] = None
    ) -> LLMResponse:
        res = self._provider.generate_answer(question, context_chunks, history)
        if isinstance(res, LLMResponse):
            return res
        return LLMResponse(
            content=str(res),
            provider=self.provider_name,
            model=self.model,
            token_usage_type="unknown"
        )


class OpenAILLMProvider(LLMProvider):
    """
    Wraps existing OpenAI LLM implementation behind the LLMProvider interface.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None
    ):
        key = api_key or settings.LLM_API_KEY
        if not key:
            raise ValueError("OpenAI API key is required for OpenAILLMProvider.")
        m = model or settings.LLM_MODEL
        b_url = base_url or settings.LLM_BASE_URL
        self._provider = InternalOpenAIProvider(api_key=key, model=m, base_url=b_url)
        self.provider_name = "openai"
        self.model = m

    def generate_answer(
        self,
        question: str,
        context_chunks: List[str],
        history: Optional[List[Message]] = None
    ) -> LLMResponse:
        res = self._provider.generate_answer(question, context_chunks, history)
        if isinstance(res, LLMResponse):
            return res
        return LLMResponse(
            content=str(res),
            provider=self.provider_name,
            model=self.model,
            token_usage_type="unknown"
        )


class MockLLMProviderAdapter(LLMProvider):
    """
    Wraps existing MockLLMProvider behind the LLMProvider interface for unit and evaluation testing.
    """

    def __init__(self):
        self._provider = InternalMockProvider()
        self.provider_name = "mock"
        self.model = "mock-grounded"

    def generate_answer(
        self,
        question: str,
        context_chunks: List[str],
        history: Optional[List[Message]] = None
    ) -> LLMResponse:
        res = self._provider.generate_answer(question, context_chunks, history)
        if isinstance(res, LLMResponse):
            return res
        return LLMResponse(
            content=str(res),
            provider=self.provider_name,
            model=self.model,
            token_usage_type="unknown"
        )

