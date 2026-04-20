"""Wrappers de Cal.com v2 (slots, bookings, reschedule, cancel).

Mapea exactamente los HTTP requests del flujo n8n en `TOOLS/`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from app.config import get_settings

BASE = "https://api.cal.com/v2"


def _headers(version: str) -> dict[str, str]:
    s = get_settings()
    return {
        "Authorization": f"Bearer {s.cal_api_key}",
        "cal-api-version": version,
        "Content-Type": "application/json",
    }


def _format_slot_mx(iso_utc: str) -> str:
    dt = datetime.fromisoformat(iso_utc.replace("Z", "+00:00")).astimezone(
        ZoneInfo("America/Mexico_City")
    )
    return dt.strftime("%I:%M %p").lstrip("0")


def _format_date_mx(date_key: str) -> str:
    y, m, d = (int(x) for x in date_key.split("-"))
    dt = datetime(y, m, d)
    months = [
        "enero", "febrero", "marzo", "abril", "mayo", "junio",
        "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
    ]
    weekdays = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
    return f"{weekdays[dt.weekday()]} {dt.day} de {months[dt.month - 1]} de {dt.year}"


async def get_slots(start_time: str, end_time: str) -> dict[str, Any]:
    """Consulta huecos disponibles. Devuelve dict con `availability_text` y `raw`."""
    s = get_settings()
    params = {"start": start_time, "end": end_time, "eventTypeId": s.cal_event_type_id}
    async with httpx.AsyncClient(timeout=30) as http:
        r = await http.get(f"{BASE}/slots", params=params, headers=_headers("2024-09-04"))
        r.raise_for_status()
        body = r.json()

    if body.get("status") != "success" or not body.get("data"):
        return {"availability_text": "No hay horarios disponibles.", "raw": body, "slots": []}

    data = body["data"]
    lines = ["Horarios disponibles:", ""]
    flat: list[dict[str, str]] = []
    for date_key in sorted(data.keys()):
        slots = data[date_key]
        if not slots:
            continue
        lines.append(f"{_format_date_mx(date_key)}:")
        for i, slot in enumerate(slots, 1):
            display = _format_slot_mx(slot["start"])
            lines.append(f"{i}. {display}")
            flat.append({"start": slot["start"], "display": display, "date": date_key})
        lines.append("")
    lines.append("¿Cuál horario te acomoda?")
    return {"availability_text": "\n".join(lines), "raw": body, "slots": flat}


async def book(
    *,
    start_time: str,
    user_name: str,
    user_email: str,
    user_phone: str,
) -> dict[str, Any]:
    """Crea booking en Cal.com. Devuelve la respuesta completa."""
    s = get_settings()
    phone = (user_phone or "+525500000000").replace("+521", "+52")
    payload = {
        "eventTypeId": s.cal_event_type_id,
        "start": start_time,
        "attendee": {
            "name": user_name,
            "email": user_email,
            "timeZone": "America/Mexico_City",
            "phoneNumber": phone,
        },
        "bookingFieldsResponses": {
            "About": "Cita agendada desde chatbot",
            "whatsapp": phone,
        },
    }
    async with httpx.AsyncClient(timeout=30) as http:
        r = await http.post(f"{BASE}/bookings", json=payload, headers=_headers("2024-08-13"))
        r.raise_for_status()
        return r.json()


async def list_bookings(email: str, status: str = "upcoming") -> list[dict[str, Any]]:
    params = {"status": status, "attendeeEmail": email}
    async with httpx.AsyncClient(timeout=30) as http:
        r = await http.get(f"{BASE}/bookings", params=params, headers=_headers("2024-06-11"))
        r.raise_for_status()
        body = r.json()
    if body.get("status") != "success":
        return []
    return body.get("data", {}).get("bookings", []) or []


async def reschedule(booking_uid: str, new_start: str) -> dict[str, Any]:
    payload = {"start": new_start}
    async with httpx.AsyncClient(timeout=30) as http:
        r = await http.post(
            f"{BASE}/bookings/{booking_uid}/reschedule",
            json=payload,
            headers=_headers("2024-08-13"),
        )
        r.raise_for_status()
        return r.json()


async def cancel(booking_uid: str, reason: str = "") -> dict[str, Any]:
    payload = {"cancellationReason": reason}
    async with httpx.AsyncClient(timeout=30) as http:
        r = await http.post(
            f"{BASE}/bookings/{booking_uid}/cancel",
            json=payload,
            headers=_headers("2024-08-13"),
        )
        r.raise_for_status()
        return r.json()
