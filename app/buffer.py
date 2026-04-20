"""Buffer de mensajes con ventana de N segundos.

Reemplaza el patrón Redis "Insertar + Wait 25s + Switch + Delete" del flujo n8n.

Uso:
    msg_id = await insert_message(chat_id, channel, payload, text=...)
    asyncio.create_task(schedule_flush(chat_id, channel, dispatch))

`schedule_flush` espera la ventana, marca como `processed=true` los mensajes
pendientes del chat y llama a `dispatch(chat_id, channel, messages)` UNA sola
vez con todos los mensajes acumulados.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog

from app.config import get_settings
from app.db import supabase

log = structlog.get_logger(__name__)

# Locks por chat para que solo UN worker procese el flush
_flush_locks: dict[str, asyncio.Lock] = {}


def _lock_for(chat_id: str) -> asyncio.Lock:
    if chat_id not in _flush_locks:
        _flush_locks[chat_id] = asyncio.Lock()
    return _flush_locks[chat_id]


async def insert_message(
    chat_id: str,
    channel: str,
    payload: dict[str, Any],
    *,
    text: str | None = None,
    media_type: str | None = None,
    media_url: str | None = None,
) -> int:
    row = {
        "chat_id": chat_id,
        "channel": channel,
        "payload": payload,
        "text": text,
        "media_type": media_type,
        "media_url": media_url,
    }
    res = await asyncio.to_thread(
        lambda: supabase().table("message_buffer").insert(row).execute()
    )
    return res.data[0]["id"]


async def fetch_pending(chat_id: str) -> list[dict[str, Any]]:
    res = await asyncio.to_thread(
        lambda: (
            supabase()
            .table("message_buffer")
            .select("*")
            .eq("chat_id", chat_id)
            .eq("processed", False)
            .order("created_at")
            .execute()
        )
    )
    return res.data or []


async def mark_processed(ids: list[int]) -> None:
    if not ids:
        return
    now = datetime.now(timezone.utc).isoformat()
    await asyncio.to_thread(
        lambda: (
            supabase()
            .table("message_buffer")
            .update({"processed": True, "processed_at": now})
            .in_("id", ids)
            .execute()
        )
    )


Dispatch = Callable[[str, str, list[dict[str, Any]]], Awaitable[None]]


async def schedule_flush(chat_id: str, channel: str, dispatch: Dispatch) -> None:
    """Espera la ventana y dispara el dispatch con los mensajes acumulados.

    Idempotente: si ya hay otro task esperando, este no hace nada nuevo
    porque la query a `fetch_pending` puede devolver vacío si otro flush ya
    los procesó.
    """
    settings = get_settings()
    await asyncio.sleep(settings.buffer_window_seconds)
    async with _lock_for(chat_id):
        pending = await fetch_pending(chat_id)
        if not pending:
            return
        ids = [row["id"] for row in pending]
        try:
            await dispatch(chat_id, channel, pending)
        finally:
            await mark_processed(ids)


async def reap_orphans(dispatch: Dispatch) -> int:
    """Worker job: procesa mensajes pendientes que llevan más que la ventana sin
    despachar (por ejemplo si el contenedor se reinició mientras dormía)."""
    settings = get_settings()
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=settings.buffer_window_seconds)
    res = await asyncio.to_thread(
        lambda: (
            supabase()
            .table("message_buffer")
            .select("*")
            .eq("processed", False)
            .lt("created_at", cutoff.isoformat())
            .order("created_at")
            .execute()
        )
    )
    rows = res.data or []
    if not rows:
        return 0

    by_chat: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        key = (row["chat_id"], row["channel"])
        by_chat.setdefault(key, []).append(row)

    count = 0
    for (chat_id, channel), msgs in by_chat.items():
        async with _lock_for(chat_id):
            ids = [m["id"] for m in msgs]
            try:
                await dispatch(chat_id, channel, msgs)
                count += len(msgs)
            except Exception:
                log.exception("reap_dispatch_failed", chat_id=chat_id)
                continue
            await mark_processed(ids)
    return count
