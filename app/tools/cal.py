"""Wrappers de Cal.com v2 (slots, bookings, reschedule, cancel).

Mapea exactamente los HTTP requests del flujo n8n en `TOOLS/`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import structlog

from app.config import get_settings

log = structlog.get_logger(__name__)

BASE = "https://api.cal.com/v2"


def _check(r: httpx.Response, op: str) -> None:
    """Raise con el body de Cal.com incluido (raise_for_status oculta detalles)."""
    if r.status_code >= 400:
        body = r.text[:800]
        log.error("cal_api_error", op=op, status=r.status_code, body=body)
        raise httpx.HTTPStatusError(
            f"Cal.com {op} {r.status_code}: {body}", request=r.request, response=r
        )


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
        _check(r, "get_slots")
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


def _normalize_phone(raw: str | None) -> str | None:
    """Devuelve el telefono en E.164 o None si no es valido.

    - Quita espacios, guiones, parentesis.
    - Asegura prefijo `+`.
    - Mexico WhatsApp viene como +521XXXXXXXXXX (con 1 movil); Cal.com /
      libphonenumber lo quieren sin el 1: +52XXXXXXXXXX (10 digitos).
    - Valida largo basico (10-15 digitos despues del +).
    """
    if not raw:
        return None
    cleaned = "".join(c for c in str(raw) if c.isdigit() or c == "+")
    if not cleaned:
        return None
    if not cleaned.startswith("+"):
        cleaned = "+" + cleaned
    # +521XXXXXXXXXX (14 chars) -> +52XXXXXXXXXX (13 chars)
    if cleaned.startswith("+521") and len(cleaned) == 14:
        cleaned = "+52" + cleaned[4:]
    digits = cleaned[1:]
    if not digits.isdigit() or not (10 <= len(digits) <= 15):
        return None
    return cleaned


async def book(
    *,
    start_time: str,
    user_name: str,
    user_email: str,
    user_phone: str,
) -> dict[str, Any]:
    """Crea booking en Cal.com. Devuelve la respuesta completa."""
    s = get_settings()
    phone = _normalize_phone(user_phone)
    attendee: dict[str, Any] = {
        "name": user_name,
        "email": user_email,
        "timeZone": "America/Mexico_City",
    }
    booking_fields: dict[str, Any] = {"About": "Cita agendada desde chatbot"}
    if phone:
        attendee["phoneNumber"] = phone
        booking_fields["whatsapp"] = phone
    else:
        log.info("cal_book_sin_telefono", raw_phone=user_phone)
    payload = {
        "eventTypeId": s.cal_event_type_id,
        "start": start_time,
        "attendee": attendee,
        "bookingFieldsResponses": booking_fields,
    }
    async with httpx.AsyncClient(timeout=30) as http:
        r = await http.post(f"{BASE}/bookings", json=payload, headers=_headers("2024-08-13"))
        _check(r, "book")
        return r.json()


async def list_bookings(email: str, status: str = "upcoming") -> list[dict[str, Any]]:
    params = {"status": status, "attendeeEmail": email}
    async with httpx.AsyncClient(timeout=30) as http:
        r = await http.get(f"{BASE}/bookings", params=params, headers=_headers("2024-06-11"))
        _check(r, "list_bookings")
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
        _check(r, "reschedule")
        return r.json()


async def cancel(booking_uid: str, reason: str = "") -> dict[str, Any]:
    payload = {"cancellationReason": reason}
    async with httpx.AsyncClient(timeout=30) as http:
        r = await http.post(
            f"{BASE}/bookings/{booking_uid}/cancel",
            json=payload,
            headers=_headers("2024-08-13"),
        )
        _check(r, "cancel")
        return r.json()
