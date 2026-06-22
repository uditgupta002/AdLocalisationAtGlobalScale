import time
from typing import Dict

class IdempotencyStore:
    def __init__(self, ttl_seconds: float = 600.0):
        self.ttl = ttl_seconds
        self.seen: Dict[str, float] = {}

    def is_duplicate(self, event_id: str) -> bool:
        self.cleanup()
        return event_id in self.seen

    def record(self, event_id: str) -> None:
        self.seen[event_id] = time.time()

    def cleanup(self) -> None:
        now = time.time()
        expired = [key for key, timestamp in self.seen.items() if now - timestamp > self.ttl]
        for key in expired:
            del self.seen[key]
