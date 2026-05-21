"""Interruptores globales por canal.

Decide si el bot procesa mensajes entrantes de cada canal: whatsapp,
instagram, messenger, telegram, webchat. Reemplaza el arm/disarm en
memoria de ManyChat por un control persistente (tabla `channel_flags`)
manejable desde el panel `/panel`.

Se cachea el estado en memoria unos segundos para no pegarle a la base
en cada webhook.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

import structlog

from app.db import supabase

log = structlog.get_logger(__name__)

TABLE = "channel_flags"
CHANNELS = ("webchat", "telegram", "whatsapp", "instagram", "messenger")
_CACHE_TTL = 10.0  # segundos

# default si un canal no tiene fila todavía: solo web y telegram encendidos.
_DEFAULTS = {
    "webchat": True,
    "telegram": True,
    "whatsapp": False,
    "instagram": False,
    "messenger": False,
}

_cache: dict[str, bool] = {}
_cache_at: float = 0.0


async def _load() -> dict[str, bool]:
    global _cache, _cache_at
    res = await asyncio.to_thread(
        lambda: supabase().table(TABLE).select("channel, enabled").execute()
    )
    flags = dict(_DEFAULTS)
    for row in res.data or []:
        ch = row.get("channel")
        if ch in flags:
            flags[ch] = bool(row.get("enabled"))
    _cache = flags
    _cache_at = time.time()
    return flags


async def all_flags(*, force: bool = False) -> dict[str, bool]:
    """Devuelve {canal: encendido}. Usa cache de ~10 s salvo `force`."""
    if force or not _cache or (time.time() - _cache_at) > _CACHE_TTL:
        try:
            return await _load()
        except Exception as e:  # noqa: BLE001
            log.warning("channel_flags_load_failed", error=str(e))
            return _cache or dict(_DEFAULTS)
    return _cache


async def is_enabled(channel: str) -> bool:
    """True si el bot debe procesar mensajes de `channel`."""
    flags = await all_flags()
    return flags.get(channel, _DEFAULTS.get(channel, False))


async def set_enabled(channel: str, enabled: bool) -> dict[str, bool]:
    """Enciende/apaga un canal y devuelve el mapa completo actualizado."""
    if channel not in CHANNELS:
        raise ValueError(f"canal desconocido: {channel}")
    payload = {
        "channel": channel,
        "enabled": bool(enabled),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await asyncio.to_thread(
        lambda: supabase().table(TABLE).upsert(payload, on_conflict="channel").execute()
    )
    log.info("channel_flag_set", channel=channel, enabled=bool(enabled))
    return await all_flags(force=True)
