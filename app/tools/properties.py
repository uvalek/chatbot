"""Búsqueda de propiedades vía RPC de Supabase (`buscar_propiedades`)."""

from __future__ import annotations

from typing import Any

import httpx

from app.config import get_settings


async def buscar_propiedades(busqueda: str) -> list[dict[str, Any]]:
    s = get_settings()
    url = f"{s.supabase_url}/rest/v1/rpc/{s.supabase_properties_rpc}"
    headers = {
        "apikey": s.supabase_service_key,
        "Authorization": f"Bearer {s.supabase_service_key}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=30) as http:
        r = await http.post(url, json={"busqueda": busqueda or ""}, headers=headers)
        r.raise_for_status()
        data = r.json()
    if isinstance(data, list):
        return data
    return []
