"""M2 — Captación y agendamiento de visitas. Tool calling con Cal.com + HubSpot."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from openai import OpenAI

from app.config import get_settings, load_prompt
from app.tools import cal, contactos

_SYSTEM = load_prompt("m2_agendamiento")

_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "consultar_disponibilidad",
            "description": "Consulta huecos disponibles en Cal.com entre dos fechas ISO UTC.",
            "parameters": {
                "type": "object",
                "properties": {
                    "startTime": {"type": "string", "description": "ISO 8601 UTC"},
                    "endTime": {"type": "string", "description": "ISO 8601 UTC"},
                },
                "required": ["startTime", "endTime"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "book_appointment",
            "description": "Reserva una visita en Cal.com y guarda el lead en la tabla `contactos` de Supabase.",
            "parameters": {
                "type": "object",
                "properties": {
                    "startTime": {"type": "string"},
                    "userName": {"type": "string"},
                    "userEmail": {"type": "string"},
                    "zona_interes": {"type": "string"},
                    "presupuesto_max": {"type": "string"},
                    "tipo_credito": {"type": "string"},
                    "propiedad_interesada_id": {
                        "type": "integer",
                        "description": "ID exacto de la propiedad (columna `id` de propiedades). Úsalo si lo conoces del historial.",
                    },
                    "propiedad_interesada_nombre": {
                        "type": "string",
                        "description": "Nombre o zona de la propiedad como fallback si no tienes el ID. El servidor resolverá el ID por similitud.",
                    },
                },
                "required": [
                    "startTime",
                    "userName",
                    "userEmail",
                    "zona_interes",
                    "presupuesto_max",
                    "tipo_credito",
                    "propiedad_interesada_nombre",
                ],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cambioCita",
            "description": "Reagenda o cancela una visita ya existente.",
            "parameters": {
                "type": "object",
                "properties": {
                    "objetivo": {"type": "string", "enum": ["reagendar", "cancelar"]},
                    "email": {"type": "string"},
                    "name": {"type": "string"},
                    "rescheduleDate": {"type": "string"},
                    "cancelDate": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["objetivo", "email", "reason"],
            },
        },
    },
]


def _client() -> OpenAI:
    return OpenAI(api_key=get_settings().openai_api_key)


def _now_cdmx() -> str:
    dt = datetime.now(ZoneInfo("America/Mexico_City"))
    return dt.strftime("%A %d de %B de %Y, %I:%M %p")


async def _cambio_cita(args: dict, user_phone: str) -> dict:
    bookings = await cal.list_bookings(args["email"])
    if not bookings:
        return {"status": "not_found", "message": "No se encontró ninguna cita."}

    target = bookings[0]
    if len(bookings) > 1 and args.get("rescheduleDate"):
        for b in bookings:
            if args["rescheduleDate"][:10] in (b.get("startTime") or ""):
                target = b
                break
    uid = target.get("uid")

    if args["objetivo"] == "reagendar":
        result = await cal.reschedule(uid, args["rescheduleDate"])
        return {"status": "rescheduled", "raw": result}
    result = await cal.cancel(uid, args.get("reason", ""))
    return {"status": "cancelled", "raw": result}


async def respond(
    user_text: str,
    history: list[dict[str, str]],
    *,
    user_phone: str = "",
    chat_id: str = "",
    canal: str = "",
) -> str:
    s = get_settings()
    system = _SYSTEM.replace("{{NOW_CDMX}}", _now_cdmx())
    msgs: list[dict] = [{"role": "system", "content": system}]
    msgs.extend(history[-15:])
    msgs.append({"role": "user", "content": user_text})

    for _ in range(6):
        def _call() -> dict:
            resp = _client().chat.completions.create(
                model=s.openai_model_brain,
                messages=msgs,  # type: ignore[arg-type]
                tools=_TOOLS,  # type: ignore[arg-type]
                temperature=0.7,
            )
            return resp.choices[0].message.model_dump()

        choice = await asyncio.to_thread(_call)
        msgs.append(choice)
        tool_calls = choice.get("tool_calls") or []
        if not tool_calls:
            return choice.get("content") or ""

        for tc in tool_calls:
            name = tc["function"]["name"]
            args = json.loads(tc["function"]["arguments"] or "{}")
            try:
                if name == "consultar_disponibilidad":
                    result = await cal.get_slots(args["startTime"], args["endTime"])
                elif name == "book_appointment":
                    booking = await cal.book(
                        start_time=args["startTime"],
                        user_name=args["userName"],
                        user_email=args["userEmail"],
                        user_phone=user_phone,
                    )
                    try:
                        await contactos.upsert_contacto(
                            nombre=args["userName"],
                            correo=args["userEmail"],
                            telefono=user_phone or None,
                            zona_interes=args.get("zona_interes") or None,
                            presupuesto_max=args.get("presupuesto_max"),
                            tipo_credito=args.get("tipo_credito") or None,
                            fecha_visita_iso=contactos.fecha_visita_from_iso_utc(
                                args["startTime"]
                            ),
                            propiedad_interesada_id=args.get("propiedad_interesada_id"),
                            propiedad_interesada_nombre=(
                                args.get("propiedad_interesada_nombre")
                                or args.get("zona_interes")  # fallback si LLM olvidó el nombre
                            ),
                            chat_id=chat_id or None,
                            canal=canal or None,
                        )
                    except Exception as e:  # noqa: BLE001
                        booking["contactos_error"] = str(e)
                    result = booking
                elif name == "cambioCita":
                    result = await _cambio_cita(args, user_phone)
                else:
                    result = {"error": f"unknown tool {name}"}
            except Exception as e:  # noqa: BLE001
                result = {"error": str(e)}

            msgs.append(
                {
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )

    return ""
