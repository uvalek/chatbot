"""HubSpot upsert de contactos con propiedades inmobiliarias.

Replica el nodo "Guardar Lead en HubSpot" del flujo n8n AGENDAMIENTO.json.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import get_settings

BASE = "https://api.hubapi.com"


def _headers() -> dict[str, str]:
    s = get_settings()
    return {
        "Authorization": f"Bearer {s.hubspot_token}",
        "Content-Type": "application/json",
    }


def _midnight_utc_ms(iso_dt: str) -> int:
    dt = datetime.fromisoformat(iso_dt.replace("Z", "+00:00")).astimezone(timezone.utc)
    midnight = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(midnight.timestamp() * 1000)


async def upsert_contact(
    *,
    email: str,
    user_name: str,
    user_phone: str,
    booking_start_iso: str,
    zona_interes: str = "",
    presupuesto_max: str = "",
    tipo_credito: str = "",
) -> dict[str, Any]:
    parts = (user_name or "").split()
    first = parts[0] if parts else ""
    last = " ".join(parts[1:]) if len(parts) > 1 else ""

    properties = {
        "email": email,
        "firstname": first,
        "lastname": last,
        "phone": user_phone,
        "fecha_visita": _midnight_utc_ms(booking_start_iso),
        "etapa_seguimiento": "Visita Agendada",
        "seguimientos_enviados": "0",
        "confirmo_visita": "false",
        "zona_interes": zona_interes,
        "presupuesto_max": presupuesto_max,
        "tipo_credito": tipo_credito.lower(),
    }

    url = f"{BASE}/crm/v3/objects/contacts/{email}?idProperty=email"
    async with httpx.AsyncClient(timeout=30) as http:
        r = await http.patch(url, json={"properties": properties}, headers=_headers())
        if r.status_code == 404:
            r = await http.post(
                f"{BASE}/crm/v3/objects/contacts",
                json={"properties": properties},
                headers=_headers(),
            )
        r.raise_for_status()
        return r.json()
