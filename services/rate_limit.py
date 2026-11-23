"""Limitador de peticiones en memoria (ventana deslizante). Suficiente para una sola instancia;
con varios workers usa Redis u otro almacén compartido."""
import time
from collections import defaultdict, deque
from typing import Deque, Dict


class RateLimiter:
    def __init__(self, max_events: int, window_seconds: int):
        self.max_events = max_events
        self.window = window_seconds
        self._events: Dict[str, Deque[float]] = defaultdict(deque)

    def _purge(self, key: str) -> Deque[float]:
        q = self._events[key]
        limite = time.monotonic() - self.window
        while q and q[0] <= limite:
            q.popleft()
        if not q:
            self._events.pop(key, None)
            return self._events[key]
        return q

    def is_blocked(self, key: str) -> bool:
        return len(self._purge(key)) >= self.max_events

    def hit(self, key: str) -> None:
        self._purge(key).append(time.monotonic())

    def check_and_hit(self, key: str) -> bool:
        """True si la petición está permitida (y la registra)."""
        if self.is_blocked(key):
            return False
        self.hit(key)
        return True

    def reset(self, key: str) -> None:
        self._events.pop(key, None)
