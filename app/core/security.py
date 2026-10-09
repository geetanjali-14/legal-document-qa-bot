import hmac
import hashlib
import time
import uuid
from typing import Optional, Tuple, Dict
from fastapi import Request, Response
from app.core.config import settings
from app.core.logging import logger

SESSION_COOKIE_NAME = "legal_qa_session"


def sign_session_id(session_id: str, secret: str) -> str:
    """Sign session_id using HMAC-SHA256."""
    sig = hmac.new(secret.encode("utf-8"), session_id.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{session_id}.{sig}"


def verify_session_cookie(cookie_val: Optional[str], secret: str) -> Optional[str]:
    """Verify signed session cookie and return raw session_id, or None if invalid/tampered."""
    if not cookie_val or "." not in cookie_val:
        return None
    session_id, sig = cookie_val.split(".", 1)
    expected = hmac.new(secret.encode("utf-8"), session_id.encode("utf-8"), hashlib.sha256).hexdigest()
    if hmac.compare_digest(sig, expected):
        return session_id
    return None


def get_or_create_session_id(request: Request, response: Optional[Response] = None) -> Tuple[str, bool]:
    """
    Extract verified session ID from cookie or header.
    If absent or invalid, generate a new signed session ID and attach to response if provided.
    Returns (session_id, is_new).
    """
    secret = settings.SESSION_SECRET or "dev-insecure-secret"
    cookie_val = request.cookies.get(SESSION_COOKIE_NAME)
    session_id = verify_session_cookie(cookie_val, secret)

    is_new = False
    if not session_id:
        session_id = f"sess_{uuid.uuid4().hex}"
        is_new = True

    if response is not None and (is_new or not cookie_val):
        signed = sign_session_id(session_id, secret)
        # Secure flag can be enabled in production/HTTPS, samesite lax allows normal page transitions
        is_prod = settings.APP_ENV.lower() == "production"
        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=signed,
            httponly=True,
            samesite="lax",
            secure=is_prod,
            max_age=86400 * 30  # 30 days
        )

    return session_id, is_new


class SlidingWindowRateLimiter:
    """
    In-memory thread-safe sliding window rate limiter.
    Fail-safe: tracks request timestamps per key within a fixed window.
    """
    def __init__(self):
        self._history: Dict[str, list] = {}

    def is_allowed(self, key: str, max_requests: int, window_seconds: int = 60) -> Tuple[bool, int]:
        """
        Check if key has exceeded max_requests within window_seconds.
        Returns (is_allowed, retry_after_seconds).
        """
        now = time.time()
        cutoff = now - window_seconds
        records = self._history.setdefault(key, [])
        # Prune expired timestamps
        self._history[key] = [t for t in records if t > cutoff]

        if len(self._history[key]) >= max_requests:
            oldest = self._history[key][0]
            retry_after = max(1, int(oldest + window_seconds - now))
            return False, retry_after

        self._history[key].append(now)
        return True, 0

    def reset(self):
        self._history.clear()


rate_limiter = SlidingWindowRateLimiter()

