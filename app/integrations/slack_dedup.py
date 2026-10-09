import time
from typing import Dict, Tuple


class EventDeduplicator:
    """
    In-memory TTL cache to deduplicate Slack retried events.
    Slack retries events if the acknowledgement takes >3s or if there is a transient network glitch.
    """

    def __init__(self, ttl_seconds: float = 60.0):
        self.ttl = ttl_seconds
        self._seen: Dict[str, float] = {}

    def is_duplicate(self, event_id: str) -> bool:
        if not event_id:
            return False
        now = time.time()
        self._cleanup(now)
        if event_id in self._seen:
            return True
        self._seen[event_id] = now
        return False

    def _cleanup(self, now: float):
        # Prune expired event IDs
        expired = [eid for eid, ts in self._seen.items() if now - ts > self.ttl]
        for eid in expired:
            del self._seen[eid]

