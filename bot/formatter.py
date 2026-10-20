"""把判斷結果排成工作人員在 LINE 上好讀的訊息。"""
from __future__ import annotations

from .brain import Decision
from .knowledge import Knowledge

LINE_TEXT_LIMIT = 5000

_HEADERS = {
    "faq": "📘 官方 FAQ",
    "judgment": "🧭 現場判斷建議",
    "escalate": "🚨 請升級處理",
    "clarify": "❓ 需要更多資訊",
}


def format_reply(d: Decision, kb: Knowledge) -> str:
    lines = [_HEADERS[d.mode]]
    if d.situation:
        lines.append(f"狀況：{d.situation}")

    if d.faq_ids:
        lines.append("")
        lines.append("【官方答案｜請照此回覆】" if d.mode == "faq" else "【相關官方 FAQ】")
        for fid in d.faq_ids:
            f = kb.by_id[fid]
            lines.append(f"〔{f.id}〕{f.question}")
            lines.append(f.answer.strip())

    if d.escalate_to:
        contact = kb.playbook.get("contacts", {}).get(d.escalate_to, "")
        lines.append("")
        lines.append(f"📞 通知：{d.escalate_to}" + (f"｜{contact}" if contact else ""))

    if d.staff_actions:
        lines.append("")
        lines.append("【你可以這樣做】" if d.mode != "clarify" else "【請補充】")
        lines += [f"{i}. {a}" for i, a in enumerate(d.staff_actions, 1)]

    if d.customer_script and d.mode != "faq":
        lines.append("")
        lines.append("【建議對客人說】")
        lines.append(d.customer_script.strip())

    footer = []
    if d.matched_rules:
        footer.append("依據規則：" + "、".join(d.matched_rules))
    if d.confidence == "low":
        footer.append("⚠️ 信心偏低，建議與主管確認")
    if footer:
        lines.append("")
        lines += footer

    text = "\n".join(lines)
    return text if len(text) <= LINE_TEXT_LIMIT else text[:LINE_TEXT_LIMIT - 20] + "\n…（內容過長已截斷）"
