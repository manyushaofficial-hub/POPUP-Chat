"""每位工作人員的短期對話記憶，讓「那如果他還是不接受呢？」這種追問能接續。"""
from __future__ import annotations

import time
from collections import defaultdict, deque


class SessionStore:
    def __init__(self, max_turns: int = 6, idle_seconds: int = 1800) -> None:
        self.max_turns = max_turns
        self.idle_seconds = idle_seconds
        self._turns: dict[str, deque] = defaultdict(lambda: deque(maxlen=max_turns))
        self._last: dict[str, float] = {}

    def history(self, user_id: str) -> list[dict]:
        if time.time() - self._last.get(user_id, 0) > self.idle_seconds:
            self._turns.pop(user_id, None)  # 閒置太久就視為新的狀況
        msgs = []
        for q, a in self._turns.get(user_id, ()):
            msgs += [{"role": "user", "content": q}, {"role": "assistant", "content": a}]
        return msgs

    def add(self, user_id: str, question: str, answer: str) -> None:
        self._turns[user_id].append((question, answer))
        self._last[user_id] = time.time()

    def clear(self, user_id: str) -> None:
        self._turns.pop(user_id, None)
