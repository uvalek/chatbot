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
import structlog

from app.config import get_settings

log = structlog.get_logger(__name__)

SEND_URL = "https://api.manychat.com/fb/sending/sendContent"
SUBSCRIBER_INFO_URL = "https://api.manychat.com/fb/subscriber/getInfo"


async def fetch_subscriber_phone(subscriber_id: str) -> str | None:
    """Pide a la API de ManyChat el telefono real del suscriptor de WhatsApp.

    Lo usamos cuando el placeholder `{{phone}}` del External Request llega sin
    resolver (campo "Telefono" vacio en el perfil) o como literal. En WhatsApp
    el numero esta siempre disponible como identificador del contacto.
    """
    settings = get_settings()
    token = settings.manychat_api_token
    if not token or not subscriber_id:
        return None
    headers = {"Authorization": f"Bearer {token}"}
    params = {"subscriber_id": str(subscriber_id)}
    try:
        async with httpx.AsyncClient(timeout=10, headers=headers) as http:
            r = await http.get(SUBSCRIBER_INFO_URL, params=params)
        if r.status_code >= 300:
            log.warning(
                "manychat_subscriber_info_error",
                status=r.status_code,
                body=r.text[:300],
                subscriber_id=subscriber_id,
            )
            return None
        body = r.json()
    except Exception as e:  # noqa: BLE001
        log.warning("manychat_subscriber_info_exception", error=str(e), subscriber_id=subscriber_id)
        return None
    if body.get("status") != "success":
        return None
    data = body.get("data") or {}
    # ManyChat devuelve `phone` (a veces sin `+`) y/o `whatsapp_phone`.
    phone = data.get("whatsapp_phone") or data.get("phone")
    if phone and not str(phone).startswith("+"):
        phone = "+" + str(phone).lstrip("0")
    return phone or None


VALID_SUBCHANNELS = ("whatsapp", "instagram", "messenger")


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

    # Sub-canal visible (whatsapp/instagram/messenger). Lo manda ManyChat en
    # cada External Request como ?channel=instagram. Default whatsapp para
    # mantener compat con el flow viejo de WA.
    subchannel = (
        body.get("channel")
        or inner.get("channel")
        or inner.get("subchannel")
        or "whatsapp"
    )
    subchannel = str(subchannel).lower().strip()
    if subchannel not in VALID_SUBCHANNELS:
        subchannel = "whatsapp"

    return {
        "chat_id": str(chat_id),
        "text": text,
        "media_type": media_type,
        "media_url": media_url,
        "subchannel": subchannel,
        "raw": inner,
    }


async def send_messages(
    chat_id: str,
    chunks: list[str],
    subchannel: str = "whatsapp",
) -> None:
    """Envia mensajes via ManyChat. `subchannel` define el `content.type`:
    whatsapp | instagram | messenger. Cada uno usa el endpoint del canal
    conectado al subscriber en ManyChat.
    """
    settings = get_settings()
    token = settings.manychat_api_token
    if not token:
        log.error("manychat_send_skipped_no_token", chat_id=chat_id)
        return
    sub = subchannel if subchannel in VALID_SUBCHANNELS else "whatsapp"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=20, headers=headers) as http:
        for i, text in enumerate(chunks):
            payload = {
                "subscriber_id": chat_id,
                "data": {
                    "version": "v2",
                    "content": {
                        "type": sub,
                        "messages": [{"type": "text", "text": text}],
                    },
                },
            }
            try:
                r = await http.post(SEND_URL, json=payload)
                if r.status_code >= 300:
                    log.error(
                        "manychat_send_error",
                        status=r.status_code,
                        body=r.text[:500],
                        chat_id=chat_id,
                    )
                else:
                    log.info(
                        "manychat_sent",
                        chat_id=chat_id,
                        chunk=i + 1,
                        total=len(chunks),
                        subchannel=sub,
                    )
            except Exception as e:  # noqa: BLE001
                log.exception("manychat_send_exception", error=str(e), chat_id=chat_id)
            if i < len(chunks) - 1:
                await asyncio.sleep(settings.send_delay_seconds)
