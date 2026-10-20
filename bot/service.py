"""處理一則工作人員訊息（LINE 與本機測試共用）。"""
from __future__ import annotations

import json
import logging
import os

import anthropic

from . import qa_log
from .brain import Brain
from .formatter import format_reply
from .knowledge import KnowledgeStore
from .session import SessionStore

log = logging.getLogger(__name__)

HELP_TEXT = """👋 我是快閃店現場助理
直接輸入客人的問題或現場狀況即可，例如：
・客人問怎麼預約？
・客人沒預約但堅持要進場，還很生氣
・刷卡機壞了，後面排了 10 個人

可用指令：
・新狀況 → 清除上下文，開始問新的事
・/faq → 查看官方 FAQ 清單
・/myid → 查看你的 LINE userId（給管理員開權限用）
管理員：/reload 重新載入 FAQ、/gaps 查看 FAQ 沒涵蓋的問題"""


def _ids(env: str) -> set[str]:
    return {x.strip() for x in os.getenv(env, "").split(",") if x.strip()}


class StaffAssistant:
    def __init__(self, store: KnowledgeStore | None = None, brain: Brain | None = None) -> None:
        self.store = store or KnowledgeStore.from_env()
        self.brain = brain or Brain()
        self.sessions = SessionStore(max_turns=int(os.getenv("HISTORY_TURNS", "6")))
        self.allowed = _ids("ALLOWED_USER_IDS")
        self.admins = _ids("ADMIN_USER_IDS")
        self.store.get()  # 啟動時就檢查設定檔格式

    def is_allowed(self, user_id: str) -> bool:
        return not self.allowed or user_id in self.allowed or user_id in self.admins

    async def handle(self, user_id: str, text: str) -> str:
        text = text.strip()
        cmd = text.lower()

        if cmd == "/myid":
            return f"你的 userId：\n{user_id}"
        if not self.is_allowed(user_id):
            return "此助理僅限現場工作人員使用。請將 /myid 顯示的 ID 提供給管理員開通。"
        if cmd in {"說明", "help", "/help", "?"}:
            return HELP_TEXT
        if cmd in {"新狀況", "重來", "/new"}:
            self.sessions.clear(user_id)
            return "好的，已清除上下文，請描述新的狀況。"
        if cmd == "/faq":
            kb = self.store.get()
            return "📘 官方 FAQ 清單\n" + "\n".join(f"〔{f.id}〕{f.question}" for f in kb.faqs)
        if cmd in {"/reload", "/gaps"}:
            if user_id not in self.admins:
                return "此指令僅限管理員使用。"
            return self._reload() if cmd == "/reload" else self._gaps()

        kb = self.store.get()
        try:
            decision = await self.brain.decide(kb, text, self.sessions.history(user_id))
        except anthropic.RateLimitError:
            return "目前查詢的人太多，請 10 秒後再試一次。緊急狀況請直接找現場主管。"
        except (anthropic.APIConnectionError, anthropic.InternalServerError):
            log.exception("Claude API 連線失敗")
            return "系統連線不穩，請稍後再試。緊急狀況請直接找現場主管。"
        except anthropic.APIStatusError:
            log.exception("Claude API 錯誤")
            return "系統發生錯誤，請稍後再試，或直接詢問現場主管。"

        reply = format_reply(decision, kb)
        self.sessions.add(user_id, text, reply)
        qa_log.record(user_id, text, decision)
        return reply

    def _reload(self) -> str:
        kb = self.store.get(force=True)
        return f"✅ 已重新載入：FAQ {len(kb.faqs)} 筆、情境規則 {len(kb.playbook.get('scenarios', []))} 條"

    def _gaps(self, limit: int = 15) -> str:
        if not qa_log.LOG_PATH.exists():
            return "目前還沒有紀錄。"
        rows = [json.loads(l) for l in qa_log.LOG_PATH.read_text(encoding="utf-8").splitlines() if l]
        gaps = [r for r in rows if r["mode"] != "faq" or r["confidence"] == "low"][-limit:]
        if not gaps:
            return "目前所有問題都有 FAQ 涵蓋 👍"
        return "📝 FAQ 未涵蓋的問題（最近 {}）\n".format(len(gaps)) + "\n".join(
            f"・{r['ts'][5:16]} {r['question'][:40]}（{r['mode']}）" for r in gaps)
