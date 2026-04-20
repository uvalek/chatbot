"""FastAPI: webhooks de Telegram y ManyChat."""

from __future__ import annotations

import asyncio
import logging

import structlog
from fastapi import FastAPI, Header, HTTPException, Request

from app import buffer
from app.channels import manychat as manychat_chan
from app.channels import telegram as telegram_chan
from app.config import get_settings
from app.graph import dispatch

settings = get_settings()
logging.basicConfig(level=settings.log_level)
log = structlog.get_logger(__name__)

app = FastAPI(title="Chatbot Home Plus")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/webhook/telegram")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> dict[str, str]:
    if (
        settings.telegram_webhook_secret
        and x_telegram_bot_api_secret_token != settings.telegram_webhook_secret
    ):
        raise HTTPException(status_code=403, detail="invalid secret")

    update = await request.json()
    parsed = telegram_chan.parse_update(update)
    if not parsed:
        return {"status": "ignored"}

    media_url = None
    if parsed["media_file_id"]:
        try:
            media_url = await telegram_chan.resolve_file_url(parsed["media_file_id"])
        except Exception as e:  # noqa: BLE001
            log.warning("telegram_file_resolve_failed", error=str(e))

    await buffer.insert_message(
        chat_id=parsed["chat_id"],
        channel="telegram",
        payload=parsed["raw"],
        text=parsed["text"],
        media_type=parsed["media_type"],
        media_url=media_url,
    )
    asyncio.create_task(buffer.schedule_flush(parsed["chat_id"], "telegram", dispatch))
    return {"status": "queued"}


@app.post("/webhook/manychat")
async def manychat_webhook(request: Request) -> dict[str, str]:
    body = await request.json()
    parsed = manychat_chan.parse_webhook(body)
    if not parsed:
        return {"status": "ignored"}

    await buffer.insert_message(
        chat_id=parsed["chat_id"],
        channel="manychat",
        payload=parsed["raw"],
        text=parsed["text"],
        media_type=parsed["media_type"],
        media_url=parsed["media_url"],
    )
    asyncio.create_task(buffer.schedule_flush(parsed["chat_id"], "manychat", dispatch))
    return {"status": "queued"}
