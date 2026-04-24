"""Upsert de leads en la tabla `contactos` de Supabase (CRM propio).

Reemplaza la integración con HubSpot. La tabla tiene la columna
`propiedad_interesada` (FK → propiedades.id), así que aceptamos:
  - `propiedad_interesada_id`: si el agente ya tiene el ID exacto.
  - `propiedad_interesada_nombre`: fallback, hacemos lookup en `propiedades`
    por nombre o zona y resolvemos al ID.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

import structlog

from app.db import supabase

log = structlog.get_logger(__name__)


async def _resolve_propiedad_id(
    propiedad_id: int | None,
    propiedad_nombre: str | None,
) -> int | None:
    if propiedad_id:
        try:
            return int(propiedad_id)
        except (TypeError, ValueError):
            pass
    if not propiedad_nombre:
        return None
    name = propiedad_nombre.strip()
    if not name:
        return None

    # 1) Match por nombre (substring)
    res = await asyncio.to_thread(
        lambda: (
            supabase()
            .table("propiedades")
            .select("id")
            .ilike("nombre", f"%{name}%")
            .limit(1)
            .execute()
        )
    )
    rows = res.data or []
    if rows:
        return int(rows[0]["id"])

    # 2) Fallback por zona
    res2 = await asyncio.to_thread(
        lambda: (
            supabase()
            .table("propiedades")
            .select("id")
            .ilike("zona", f"%{name}%")
            .limit(1)
            .execute()
        )
    )
    rows2 = res2.data or []
    if rows2:
        return int(rows2[0]["id"])

    log.warning("propiedad_no_resuelta", nombre=name)
    return None


def _to_float(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(str(v).replace(",", "").replace("$", "").strip())
    except (TypeError, ValueError):
        return None


async def upsert_contacto(
    *,
    nombre: str,
    correo: str,
    telefono: str | None = None,
    zona_interes: str | None = None,
    presupuesto_max: Any = None,
    tipo_credito: str | None = None,
    fecha_visita_iso: str | None = None,
    propiedad_interesada_id: int | None = None,
    propiedad_interesada_nombre: str | None = None,
    etapa_seguimiento: str = "visita_agendada",
    chat_id: str | None = None,
    canal: str | None = None,
) -> dict[str, Any]:
    propiedad_id = await _resolve_propiedad_id(
        propiedad_interesada_id, propiedad_interesada_nombre
    )

    payload: dict[str, Any] = {
        "nombre": nombre,
        "etapa_seguimiento": etapa_seguimiento,
    }
    if correo:
        payload["correo"] = correo
    if telefono:
        payload["telefono"] = telefono
    if zona_interes:
        payload["zona_interes"] = zona_interes
    pmax = _to_float(presupuesto_max)
    if pmax is not None:
        payload["presupuesto_max"] = pmax
    if tipo_credito:
        payload["tipo_credito"] = tipo_credito
    if fecha_visita_iso:
        # acepta string ISO; Supabase parsea timestamptz
        payload["fecha_visita"] = fecha_visita_iso
    if propiedad_id is not None:
        payload["propiedad_interesada"] = propiedad_id
    if chat_id:
        payload["chat_id"] = chat_id
    if canal:
        payload["canal"] = canal

    # En WhatsApp el telefono es el mejor identificador legible para el dashboard.
    # Si tenemos telefono, lo proponemos como handle; mas abajo solo lo escribimos
    # cuando el handle existente este vacio (no pisamos lo que ya este puesto).
    handle_candidate = telefono if (canal == "whatsapp" and telefono) else None

    # Upsert manual por correo (no hay unique constraint)
    if correo:
        existing = await asyncio.to_thread(
            lambda: (
                supabase()
                .table("contactos")
                .select("id, handle")
                .eq("correo", correo)
                .limit(1)
                .execute()
            )
        )
        rows = existing.data or []
        if rows:
            cid = rows[0]["id"]
            if handle_candidate and not (rows[0].get("handle") or "").strip():
                payload["handle"] = handle_candidate
            res = await asyncio.to_thread(
                lambda: (
                    supabase()
                    .table("contactos")
                    .update(payload)
                    .eq("id", cid)
                    .execute()
                )
            )
            log.info("contacto_actualizado", id=cid, correo=correo, propiedad=propiedad_id)
            return (res.data or [{"id": cid}])[0]

    if handle_candidate:
        payload.setdefault("handle", handle_candidate)
    res = await asyncio.to_thread(
        lambda: supabase().table("contactos").insert(payload).execute()
    )
    log.info("contacto_creado", correo=correo, propiedad=propiedad_id)
    return (res.data or [{}])[0]


async def merge_lead_fields(
    *,
    chat_id: str,
    canal: str,
    fields: dict[str, Any],
) -> dict[str, Any] | None:
    """Inserta o actualiza `contactos` por chat_id sin sobrescribir.

    Reglas:
    - Si la fila no existe, la crea con todos los campos provistos.
    - Si existe, solo escribe los campos cuyo valor actual es NULL/vacio.
      Asi el asesor puede editar manualmente y el bot no le pisa los datos.
    """
    if not chat_id or not fields:
        return None

    existing = await asyncio.to_thread(
        lambda: (
            supabase()
            .table("contactos")
            .select("id, nombre, telefono, correo, zona_interes, presupuesto_max, tipo_credito, etapa_seguimiento")
            .eq("chat_id", chat_id)
            .limit(1)
            .execute()
        )
    )
    rows = existing.data or []

    if not rows:
        # Crear nuevo
        payload: dict[str, Any] = {"chat_id": chat_id, "canal": canal}
        for k, v in fields.items():
            if v not in (None, ""):
                payload[k] = v
        # nombre ya es nullable; el dashboard cae en handle/chat_id como fallback.
        # No metemos chat_id como nombre porque no es un nombre real.
        payload.setdefault("etapa_seguimiento", fields.get("etapa_seguimiento") or "nuevo")
        res = await asyncio.to_thread(
            lambda: supabase().table("contactos").insert(payload).execute()
        )
        log.info("contacto_lead_creado", chat_id=chat_id, fields=list(payload.keys()))
        return (res.data or [{}])[0]

    row = rows[0]
    cid = row["id"]
    update: dict[str, Any] = {}
    for k, v in fields.items():
        if v in (None, ""):
            continue
        cur = row.get(k)
        if cur in (None, ""):
            update[k] = v

    if not update:
        return row

    res = await asyncio.to_thread(
        lambda: (
            supabase()
            .table("contactos")
            .update(update)
            .eq("id", cid)
            .execute()
        )
    )
    log.info("contacto_lead_actualizado", chat_id=chat_id, fields=list(update.keys()))
    return (res.data or [{"id": cid}])[0]


def fecha_visita_from_iso_utc(iso_utc: str) -> str | None:
    """Devuelve un ISO timestamptz que Supabase puede insertar tal cual."""
    if not iso_utc:
        return None
    try:
        dt = datetime.fromisoformat(iso_utc.replace("Z", "+00:00"))
        return dt.isoformat()
    except (TypeError, ValueError):
        return None
