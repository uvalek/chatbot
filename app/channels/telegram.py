"""Adapter del canal Telegram.

- `parse_update`: convierte el webhook de Telegram a (chat_id, text, media_type, media_url).
- `send_messages`: envía cada chunk con `sendChatAction` + `sendMessage` y delay.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.config import get_settings

API = "https://api.telegram.org/bot{token}"
FILE_API = "https://api.telegram.org/file/bot{token}"


def _api(path: str) -> str:
    token = get_settings().telegram_bot_token
    return API.format(token=token) + path


def parse_update(update: dict[str, Any]) -> dict[str, Any] | None:
    """Devuelve un dict con los campos relevantes o None si el update no es procesable."""
    msg = update.get("message") or update.get("edited_message")
    if not msg:
        return None
    chat = msg.get("chat") or {}
    chat_id = str(chat.get("id"))
    sender = msg.get("from") or {}
    # Identificador legible para el dashboard: @username o nombre real.
    handle: str | None = None
    uname = (sender.get("username") or "").strip().lstrip("@")
    if uname:
        handle = f"@{uname}"
    else:
        first = (sender.get("first_name") or "").strip()
        last = (sender.get("last_name") or "").strip()
        full = f"{first} {last}".strip()
        if full:
            handle = full
    out: dict[str, Any] = {
        "chat_id": chat_id,
        "text": None,
        "media_type": None,
        "media_file_id": None,
        "handle": handle,
        "raw": msg,
    }
    if "text" in msg:
        out["text"] = msg["text"]
    elif "voice" in msg:
        out["media_type"] = "audio"
        out["media_file_id"] = msg["voice"]["file_id"]
    elif "audio" in msg:
        out["media_type"] = "audio"
        out["media_file_id"] = msg["audio"]["file_id"]
    elif "photo" in msg:
        out["media_type"] = "image"
        out["media_file_id"] = msg["photo"][-1]["file_id"]
    elif "document" in msg:
        mime = msg["document"].get("mime_type", "")
        if mime.startswith("image/"):
            out["media_type"] = "image"
        elif mime.startswith("audio/") or mime.startswith("video/"):
            out["media_type"] = "audio"
        out["media_file_id"] = msg["document"]["file_id"]
    return out


async def resolve_file_url(file_id: str) -> str:
    token = get_settings().telegram_bot_token
    async with httpx.AsyncClient(timeout=15) as http:
        r = await http.get(_api("/getFile"), params={"file_id": file_id})
        r.raise_for_status()
        path = r.json()["result"]["file_path"]
    return f"{FILE_API.format(token=token)}/{path}"


async def send_messages(chat_id: str, chunks: list[str]) -> None:
    settings = get_settings()
    if not chunks:
        return
    async with httpx.AsyncClient(timeout=20) as http:
        for i, text in enumerate(chunks):
            try:
                await http.post(
                    _api("/sendChatAction"),
                    json={"chat_id": chat_id, "action": "typing"},
                )
            except httpx.HTTPError:
                pass
            await http.post(
                _api("/sendMessage"),
                json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            )
            if i < len(chunks) - 1:
                await asyncio.sleep(settings.send_delay_seconds)
