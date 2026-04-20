"""Adapter del canal ManyChat (WhatsApp).

El flujo n8n recibe un webhook genérico (POST) con `body.key`, `body.id`
(subscriber_id), texto, y posibles URLs de media (audio/imagen).

ManyChat outbound usa `https://api.manychat.com/fb/sending/sendContent` con
el subscriber_id y un payload `data.version: v2` con tipo `whatsapp`.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.config import get_settings

SEND_URL = "https://api.manychat.com/fb/sending/sendContent"


def parse_webhook(body: dict[str, Any]) -> dict[str, Any] | None:
    inner = body.get("body") if isinstance(body.get("body"), dict) else body
    chat_id = (
        inner.get("id")
        or inner.get("subscriber_id")
        or inner.get("key")
        or inner.get("contact", {}).get("id")
    )
    if chat_id is None:
        return None
    text = inner.get("text") or inner.get("message") or inner.get("last_input_text")

    media_type = None
    media_url = None
    last = inner.get("last_interaction") or {}
    mime = (last.get("mime_type") or last.get("type") or "").lower()
    url = last.get("url") or inner.get("audio_url") or inner.get("image_url")
    if url:
        if "image" in mime or url.endswith((".jpg", ".jpeg", ".png", ".webp")):
            media_type = "image"
        elif "audio" in mime or "video" in mime or url.endswith((".mp3", ".ogg", ".mp4", ".m4a")):
            media_type = "audio"
        media_url = url

    return {
        "chat_id": str(chat_id),
        "text": text,
        "media_type": media_type,
        "media_url": media_url,
        "raw": inner,
    }


async def send_messages(chat_id: str, chunks: list[str]) -> None:
    settings = get_settings()
    token = settings.manychat_api_token
    if not token:
        return
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=20, headers=headers) as http:
        for i, text in enumerate(chunks):
            payload = {
                "subscriber_id": chat_id,
                "data": {
                    "version": "v2",
                    "content": {
                        "type": "whatsapp",
                        "messages": [{"type": "text", "text": text}],
                    },
                },
                "message_tag": "ACCOUNT_UPDATE",
            }
            await http.post(SEND_URL, json=payload)
            if i < len(chunks) - 1:
                await asyncio.sleep(settings.send_delay_seconds)
