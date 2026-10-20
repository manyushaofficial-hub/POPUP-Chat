"""載入 FAQ 與 Playbook，並在檔案/試算表更新時自動重新載入。"""
from __future__ import annotations

import csv
import io
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import yaml

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class FaqEntry:
    id: str
    category: str
    question: str
    answer: str
    keywords: tuple[str, ...] = ()


@dataclass
class Knowledge:
    faqs: list[FaqEntry]
    playbook: dict
    version: str  # 內容有變動時才改變，用來判斷要不要重建 prompt
    by_id: dict[str, FaqEntry] = field(init=False)

    def __post_init__(self) -> None:
        self.by_id = {f.id: f for f in self.faqs}


def _parse_keywords(raw) -> tuple[str, ...]:
    if not raw:
        return ()
    if isinstance(raw, str):
        raw = re.split(r"[,，、;；/\n]", raw)
    return tuple(str(k).strip() for k in raw if str(k).strip())


def _to_entries(rows: list[dict]) -> list[FaqEntry]:
    entries, seen = [], set()
    for i, row in enumerate(rows, 1):
        fid = str(row.get("id") or f"FAQ{i:03d}").strip()
        q = str(row.get("question") or "").strip()
        a = str(row.get("answer") or "").strip()
        if not q or not a:
            log.warning("FAQ 第 %d 筆缺少 question 或 answer，已略過", i)
            continue
        if fid in seen:
            log.warning("FAQ id 重複：%s（後者已略過）", fid)
            continue
        seen.add(fid)
        entries.append(FaqEntry(fid, str(row.get("category") or "").strip(), q, a,
                                _parse_keywords(row.get("keywords"))))
    return entries


class KnowledgeStore:
    def __init__(self, faq_path: str, playbook_path: str,
                 sheet_url: str = "", sheet_ttl: int = 300) -> None:
        self.faq_path = Path(faq_path)
        self.playbook_path = Path(playbook_path)
        self.sheet_url = sheet_url.strip()
        self.sheet_ttl = sheet_ttl
        self._cache: Knowledge | None = None
        self._sig: tuple | None = None
        self._sheet_rows: list[dict] | None = None
        self._sheet_fetched_at = 0.0
        self._sheet_text = ""

    @classmethod
    def from_env(cls) -> "KnowledgeStore":
        return cls(
            os.getenv("FAQ_PATH", "config/faq.yaml"),
            os.getenv("PLAYBOOK_PATH", "config/playbook.yaml"),
            os.getenv("FAQ_SHEET_CSV_URL", ""),
            int(os.getenv("FAQ_SHEET_TTL_SECONDS", "300")),
        )

    def _fetch_sheet(self, force: bool) -> None:
        if not force and self._sheet_rows is not None \
                and time.time() - self._sheet_fetched_at < self.sheet_ttl:
            return
        try:
            resp = httpx.get(self.sheet_url, timeout=10, follow_redirects=True)
            resp.raise_for_status()
            text = resp.content.decode("utf-8-sig")
            self._sheet_rows = list(csv.DictReader(io.StringIO(text)))
            self._sheet_text = text
        except Exception:
            log.exception("讀取 Google 試算表 FAQ 失敗，沿用上一版")
            if self._sheet_rows is None:
                raise
        self._sheet_fetched_at = time.time()

    def get(self, force: bool = False) -> Knowledge:
        if self.sheet_url:
            self._fetch_sheet(force)
            faq_sig = hash(self._sheet_text)
        else:
            faq_sig = self.faq_path.stat().st_mtime_ns
        sig = (faq_sig, self.playbook_path.stat().st_mtime_ns)

        if self._cache is None or force or sig != self._sig:
            if self.sheet_url:
                rows = self._sheet_rows or []
            else:
                rows = yaml.safe_load(self.faq_path.read_text(encoding="utf-8")) or []
            playbook = yaml.safe_load(self.playbook_path.read_text(encoding="utf-8")) or {}
            self._cache = Knowledge(_to_entries(rows), playbook, version=str(sig))
            self._sig = sig
            log.info("已載入 %d 筆 FAQ、%d 條情境規則",
                     len(self._cache.faqs), len(playbook.get("scenarios", [])))
        return self._cache
