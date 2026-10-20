"""記錄每次問答。FAQ 沒涵蓋或信心低的問題，可用來補充下一版 FAQ。"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .brain import Decision

LOG_PATH = Path("logs/questions.jsonl")


def record(user_id: str, question: str, d: Decision) -> None:
    LOG_PATH.parent.mkdir(exist_ok=True)
    row = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "user": user_id, "question": question,
           **d.model_dump(include={"mode", "faq_ids", "matched_rules", "escalate_to", "confidence"})}
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
