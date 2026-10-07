"""
Custom exceptions and error categories for hard resource and token boundaries (OPT-021).
"""


class ResourceLimitError(ValueError):
    """Base exception for all hard resource boundary violations."""
    def __init__(self, message: str, error_category: str):
        super().__init__(message)
        self.message = message
        self.error_category = error_category


class FileSizeLimitExceededError(ResourceLimitError):
    """Raised when uploaded file size in bytes exceeds MAX_FILE_SIZE_MB."""
    def __init__(self, message: str):
        super().__init__(message, error_category="file_too_large")


class PageLimitExceededError(ResourceLimitError):
    """Raised when PDF page count exceeds MAX_DOCUMENT_PAGES."""
    def __init__(self, message: str):
        super().__init__(message, error_category="page_limit_exceeded")


class ChunkLimitExceededError(ResourceLimitError):
    """Raised when generated chunk count exceeds MAX_CHUNKS_PER_DOC."""
    def __init__(self, message: str):
        super().__init__(message, error_category="chunk_limit_exceeded")


class QueryLimitExceededError(ResourceLimitError):
    """Raised when user query characters/tokens exceed MAX_QUERY_CHARS."""
    def __init__(self, message: str):
        super().__init__(message, error_category="query_too_large")


class ContextLimitExceededError(ResourceLimitError):
    """Raised when retrieved context size or top_k exceeds MAX_CONTEXT_CHARS / MAX_TOP_K."""
    def __init__(self, message: str):
        super().__init__(message, error_category="context_limit_exceeded")


class TokenBudgetExceededError(ResourceLimitError):
    """Raised when total assembled prompt tokens exceed MAX_PROMPT_TOKENS."""
    def __init__(self, message: str):
        super().__init__(message, error_category="token_budget_exceeded")


class EmbeddingDimensionMismatchError(ValueError):
    """Raised when query vector dimension does not match indexed document vectors."""
    def __init__(self, message: str, query_dim: int, store_dim: int):
        super().__init__(message)
        self.message = message
        self.query_dim = query_dim
        self.store_dim = store_dim

