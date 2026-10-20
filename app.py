"""LINE Webhook 伺服器。

啟動：uvicorn app:app --host 0.0.0.0 --port 8000
LINE Developers Console 的 Webhook URL 設為：https://<你的網域>/callback
"""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from linebot.v3 import WebhookParser
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    ApiException,
    AsyncApiClient,
    AsyncMessagingApi,
    Configuration,
    PushMessageRequest,
    ReplyMessageRequest,
    ShowLoadingAnimationRequest,
    TextMessage,
)
from linebot.v3.webhooks import FollowEvent, MessageEvent, TextMessageContent

from bot.service import HELP_TEXT, StaffAssistant

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")

parser = WebhookParser(os.environ["LINE_CHANNEL_SECRET"])
assistant = StaffAssistant()
GROUP_TRIGGER = os.getenv("GROUP_TRIGGER", "?")
line_api: AsyncMessagingApi


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # LINE 的 async client 必須在 event loop 啟動後建立
    global line_api
    api_client = AsyncApiClient(Configuration(access_token=os.environ["LINE_CHANNEL_ACCESS_TOKEN"]))
    line_api = AsyncMessagingApi(api_client)
    yield
    await api_client.close()


app = FastAPI(lifespan=lifespan)
_tasks: set[asyncio.Task] = set()


@app.get("/")
async def health():
    return {"ok": True}


@app.post("/callback")
async def callback(request: Request):
    signature = request.headers.get("X-Line-Signature", "")
    body = (await request.body()).decode("utf-8")
    try:
        events = parser.parse(body, signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    # 先回 200 給 LINE，再於背景處理（Claude 判斷需要幾秒）
    for event in events:
        task = asyncio.create_task(handle_event(event))
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)
    return "OK"


async def handle_event(event) -> None:
    try:
        if isinstance(event, FollowEvent):
            await send(event, HELP_TEXT)
            return
        if not (isinstance(event, MessageEvent) and isinstance(event.message, TextMessageContent)):
            return

        text = event.message.text
        user_id = event.source.user_id or ""
        if event.source.type in ("group", "room"):
            triggers = (GROUP_TRIGGER, "？") if GROUP_TRIGGER == "?" else (GROUP_TRIGGER,)
            if not text.startswith(triggers):
                return
            text = text[1:] if text[0] in "?？" else text[len(GROUP_TRIGGER):]
        else:
            await show_loading(user_id)

        reply = await assistant.handle(user_id, text)
        await send(event, reply)
    except Exception:
        log.exception("處理訊息失敗")


async def show_loading(user_id: str) -> None:
    try:
        await line_api.show_loading_animation(
            ShowLoadingAnimationRequest(chat_id=user_id, loading_seconds=20))
    except ApiException:
        pass  # 只是視覺提示，失敗不影響回覆


async def send(event, text: str) -> None:
    messages = [TextMessage(text=text)]
    try:
        await line_api.reply_message(
            ReplyMessageRequest(reply_token=event.reply_token, messages=messages))
    except ApiException as e:
        # reply token 約 1 分鐘失效；逾時就改用 push 發送
        log.warning("Reply 失敗（%s），改用 push", e.status)
        src = event.source
        to = getattr(src, "group_id", None) or getattr(src, "room_id", None) or src.user_id
        await line_api.push_message(PushMessageRequest(to=to, messages=messages))
