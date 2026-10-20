"""FAQ 搜尋：以中文雙字詞 + 關鍵字比對，找出最相關的官方 FAQ 候選。

不需要外部服務，FAQ 數量在數百筆內都很快。搜尋結果會提供給 Claude
作為「優先參考」，最終是否引用由 Claude 判斷，引用時一律顯示原文。
"""
from __future__ import annotations

import re

from .knowledge import FaqEntry

_PUNCT = re.compile(r"[\s\W_]+", re.UNICODE)


def _normalize(text: str) -> str:
    return _PUNCT.sub("", text.lower())


def _bigrams(text: str) -> set[str]:
    t = _normalize(text)
    if len(t) < 2:
        return {t} if t else set()
    return {t[i:i + 2] for i in range(len(t) - 1)}


def search(query: str, faqs: list[FaqEntry], top_k: int = 5,
           min_score: float = 0.15) -> list[tuple[FaqEntry, float]]:
    q_norm = _normalize(query)
    q_grams = _bigrams(query)
    if not q_grams:
        return []

    scored = []
    for faq in faqs:
        doc_grams = _bigrams(faq.question) | _bigrams(" ".join(faq.keywords))
        overlap = len(q_grams & doc_grams) / len(q_grams)
        # 關鍵字完整出現在問句中，加權
        kw_hits = sum(1 for k in faq.keywords if _normalize(k) and _normalize(k) in q_norm)
        score = overlap + 0.35 * kw_hits
        if score >= min_score:
            scored.append((faq, round(score, 3)))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]
