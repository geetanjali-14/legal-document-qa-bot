from abc import ABC, abstractmethod
from typing import List, Optional
import re
import httpx
from app.models.chat import Message
from app.core.config import settings
from app.core.logging import logger

SYSTEM_PROMPT = """You are a document-grounded legal information assistant.

Answer the user's question using ONLY the provided document context below.
Do not use unsupported facts.
Do not invent clauses, dates, amounts, obligations, rights, or legal conclusions.
If the answer cannot be determined from the provided context, explicitly state:
"I couldn't find enough information in the uploaded document to answer this question."

Do not pretend that information exists when it does not.
Distinguish between what the document explicitly states and what is an interpretation.
Do not provide legal advice.
When stating facts, cite the relevant document, page, and section based on the context provided.
"""


class BaseLLMProvider(ABC):
    @abstractmethod
    def generate_answer(
        self,
        question: str,
        context_chunks: List[str],
        history: Optional[List[Message]] = None
    ) -> str:
        pass


class MockLLMProvider(BaseLLMProvider):
    """
    Deterministic rule-grounded mock provider for automated testing and offline verification.
    Directly extracts relevant facts from the provided context, refusing if context is missing.
    """
    def generate_answer(
        self,
        question: str,
        context_chunks: List[str],
        history: Optional[List[Message]] = None
    ) -> str:
        if not context_chunks:
            return "I couldn't find enough information in the uploaded document to answer this question."

        combined_context = "\n".join(context_chunks)
        lower_q = question.lower()
        lower_ctx = combined_context.lower()

        # If question words aren't substantially in context, refuse
        q_words = [w for w in lower_q.replace("?", "").split() if len(w) > 3 and w not in {"what", "when", "where", "which", "does", "have", "with", "this", "that"}]
        matching_words = [w for w in q_words if w in lower_ctx]

        if q_words and (len(matching_words) / len(q_words)) < 0.25:
            return "I couldn't find enough information in the uploaded document to answer this question."

        # Extract sentences using robust sentence-boundary detection
        sentences = re.split(r'(?<=[a-zA-Z][.!?])\s+|\n+', combined_context)
        scored_sentences = []
        for s in sentences:
            s_clean = s.strip()
            if not s_clean:
                continue
            s_lower = s_clean.lower()
            matches = sum(1 for w in q_words if w in s_lower or (len(w) > 5 and w[:5] in s_lower))
            if matches > 0:
                s_fmt = s_clean if s_clean.endswith(".") else s_clean + "."
                scored_sentences.append((matches, s_fmt))

        if scored_sentences:
            scored_sentences.sort(key=lambda x: x[0], reverse=True)
            top_sentences = [s for _, s in scored_sentences[:3]]
            return "Based on the provided document: " + " ".join(top_sentences)

        return "I couldn't find enough information in the uploaded document to answer this question."


class OpenAILLMProvider(BaseLLMProvider):
    def __init__(self, api_key: str, model: str = "gpt-4o-mini", base_url: str = ""):
        self.api_key = api_key
        self.model = model
        self.base_url = (base_url or "https://api.openai.com/v1").rstrip("/") + "/chat/completions"

    def generate_answer(
        self,
        question: str,
        context_chunks: List[str],
        history: Optional[List[Message]] = None
    ) -> str:
        if not context_chunks:
            return "I couldn't find enough information in the uploaded document to answer this question."

        context_str = "\n\n---\n\n".join(context_chunks)
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
        ]

        if history:
            for msg in history[-4:]:  # Keep recent history
                messages.append({"role": msg.role, "content": msg.content})

        prompt_content = f"CONTEXT FROM UPLOADED DOCUMENT:\n{context_str}\n\nQUESTION: {question}"
        messages.append({"role": "user", "content": prompt_content})

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": settings.LLM_TEMPERATURE,
            "max_tokens": settings.LLM_MAX_TOKENS
        }

        with httpx.Client(timeout=45.0) as client:
            resp = client.post(self.base_url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()


class LLMService:
    def __init__(self):
        self.provider = self._resolve_provider()

    def _resolve_provider(self) -> BaseLLMProvider:
        provider_name = settings.LLM_PROVIDER.lower()
        logger.info(f"Initializing LLM provider: {provider_name}")

        if provider_name == "openai":
            if not settings.LLM_API_KEY:
                logger.warning("LLM_API_KEY missing for OpenAI. Falling back to MockLLMProvider.")
                return MockLLMProvider()
            return OpenAILLMProvider(
                api_key=settings.LLM_API_KEY,
                model=settings.LLM_MODEL,
                base_url=settings.LLM_BASE_URL
            )
        else:
            return MockLLMProvider()

    def generate_answer(
        self,
        question: str,
        context_chunks: List[str],
        history: Optional[List[Message]] = None
    ) -> str:
        return self.provider.generate_answer(question, context_chunks, history)
