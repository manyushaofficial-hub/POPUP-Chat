"""離線測試（不呼叫真的 Claude API）：python -m pytest -q"""
import asyncio
import json
from types import SimpleNamespace

import pytest

from bot import qa_log
from bot.brain import Brain, build_system_prompt
from bot.faq_search import search
from bot.knowledge import KnowledgeStore
from bot.service import StaffAssistant


@pytest.fixture(autouse=True)
def tmp_log(tmp_path, monkeypatch):
    monkeypatch.setattr(qa_log, "LOG_PATH", tmp_path / "q.jsonl")


@pytest.fixture
def store():
    return KnowledgeStore("config/faq.yaml", "config/playbook.yaml")


class FakeClient:
    """模擬 Claude 回傳指定的 JSON。"""
    def __init__(self, payload):
        self.payload = payload
        self.calls = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(stop_reason="end_turn", stop_details=None,
                               content=[SimpleNamespace(type="text", text=json.dumps(self.payload))])


def decision(**kw):
    base = dict(mode="judgment", faq_ids=[], situation="", matched_rules=[], staff_actions=[],
                customer_script="", escalate_to="", confidence="high")
    return base | kw


def test_faq_loaded(store):
    kb = store.get()
    assert len(kb.faqs) == 10 and "R01" in kb.by_id


@pytest.mark.parametrize("q,expected", [
    ("客人問要怎麼預約", "R01"),
    ("他沒預約可以直接進去嗎", "R02"),
    ("可以刷卡嗎", "S01"),
    ("可以帶狗進去嗎", "G02"),
    ("客人遲到了20分鐘", "R04"),
])
def test_search(store, q, expected):
    hits = search(q, store.get().faqs)
    assert hits and hits[0][0].id == expected, hits


def test_system_prompt_contains_all_faq(store):
    kb = store.get()
    prompt = build_system_prompt(kb)
    assert all(f"[{f.id}]" in prompt for f in kb.faqs)
    assert "ANGRY" in prompt


def test_faq_answer_is_verbatim(store):
    fake = FakeClient(decision(mode="faq", faq_ids=["R01"], situation="詢問預約方式"))
    bot = StaffAssistant(store, Brain(fake))
    reply = asyncio.run(bot.handle("u1", "客人問怎麼預約"))
    assert store.get().by_id["R01"].answer.strip() in reply
    assert "官方答案" in reply
    req = fake.calls[0]
    assert req["fallbacks"] == "default"
    assert req["system"][0]["cache_control"] == {"type": "ephemeral"}


def test_unknown_faq_id_is_dropped(store):
    fake = FakeClient(decision(mode="faq", faq_ids=["X99"]))
    reply = asyncio.run(StaffAssistant(store, Brain(fake)).handle("u1", "測試"))
    assert "X99" not in reply and "信心偏低" in reply


def test_escalation_shows_contact(store):
    fake = FakeClient(decision(mode="escalate", escalate_to="現場主管", matched_rules=["ANGRY"],
                               staff_actions=["引導到旁邊"], customer_script="非常抱歉讓您不愉快"))
    reply = asyncio.run(StaffAssistant(store, Brain(fake)).handle("u1", "客人很生氣要見主管"))
    assert "王店長" in reply and "非常抱歉" in reply and "ANGRY" in reply


def test_history_is_sent_on_followup(store):
    fake = FakeClient(decision(staff_actions=["a"]))
    bot = StaffAssistant(store, Brain(fake))
    asyncio.run(bot.handle("u1", "第一個問題"))
    asyncio.run(bot.handle("u1", "那如果他還是不接受呢"))
    msgs = fake.calls[1]["messages"]
    assert len(msgs) == 3 and msgs[0]["content"] == "第一個問題"


def test_access_control(store, monkeypatch):
    monkeypatch.setenv("ALLOWED_USER_IDS", "staff1")
    bot = StaffAssistant(store, Brain(FakeClient(decision())))
    assert "僅限" in asyncio.run(bot.handle("stranger", "怎麼預約"))
    assert "stranger" in asyncio.run(bot.handle("stranger", "/myid"))
