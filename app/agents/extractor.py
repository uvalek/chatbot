"""Extractor de datos del lead.

Despues de cada turno corre un mini-LLM con structured output sobre los
ultimos N mensajes para extraer:

  - nombre
  - zona_interes (texto, ej. "Apizaco", "Tlaxcala centro")
  - presupuesto_max (numero MXN)
  - tipo_credito ("infonavit" | "fovissste" | "bancario" | "contado" | "otro")
  - etapa_sugerida ("nuevo" | "calificado" | "visita_agendada" | "visito" | "cerrado")
  - correo
  - telefono

Devuelve solo los campos que pudo inferir con alta confianza. Los None se
ignoran y NO sobrescriben datos previos en `contactos`.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import structlog
from openai import OpenAI

from app.config import get_settings

log = structlog.get_logger(__name__)


_SYSTEM = """Eres un extractor de datos para un CRM inmobiliario en Mexico.
Lees el ultimo mensaje del usuario y, opcionalmente, el historial reciente,
y devuelves un JSON con los datos del prospecto que puedas inferir con alta
confianza.

REGLAS:
- Si un campo NO esta claro, devuelvelo como null. Mejor null que adivinar.
- presupuesto_max: numero entero en pesos mexicanos (ej. "4 millones" -> 4000000,
  "1.5M" -> 1500000, "500 mil" -> 500000). Si solo dice "barato" o "no se", null.
- tipo_credito: uno de ["infonavit","fovissste","bancario","contado","otro"]
  (minusculas). "credito de mi trabajo" en Mexico suele ser infonavit. null si dudas.
- zona_interes: nombre corto de la ciudad/colonia/zona (ej. "Apizaco", "Tlaxcala centro").
  Si solo dice "centro" sin ciudad, null.
- etapa_sugerida: usa heuristica conservadora.
    * "nuevo": acaba de llegar, solo saludo
    * "calificado": dio presupuesto + tipo_credito + zona
    * "visita_agendada": confirmo fecha y hora de visita
    * "visito": dijo que ya visito la propiedad
    * "cerrado": ya compro / desistio
  Si no estas seguro, null (no degrades).
- nombre: solo si el usuario lo dijo explicitamente ("me llamo Juan", "soy Maria").
- correo, telefono: solo si el usuario los escribio en el mensaje.

Responde SIEMPRE con un JSON valido con exactamente estas llaves:
{"nombre": str|null, "zona_interes": str|null, "presupuesto_max": int|null,
 "tipo_credito": str|null, "etapa_sugerida": str|null, "correo": str|null,
 "telefono": str|null}
"""


_VALID_CREDITO = {"infonavit", "fovissste", "bancario", "contado", "otro"}
_VALID_ETAPA = {"nuevo", "calificado", "visita_agendada", "visito", "cerrado"}


def _client() -> OpenAI:
    return OpenAI(api_key=get_settings().openai_api_key)


def _coerce(raw: dict[str, Any]) -> dict[str, Any]:
    """Normaliza y descarta valores invalidos o vacios."""
    out: dict[str, Any] = {}
    for k in ("nombre", "zona_interes", "correo", "telefono"):
        v = raw.get(k)
        if isinstance(v, str) and v.strip():
            out[k] = v.strip()
    pmax = raw.get("presupuesto_max")
    if isinstance(pmax, (int, float)) and pmax > 0:
        out["presupuesto_max"] = int(pmax)
    tc = raw.get("tipo_credito")
    if isinstance(tc, str) and tc.lower().strip() in _VALID_CREDITO:
        out["tipo_credito"] = tc.lower().strip()
    et = raw.get("etapa_sugerida")
    if isinstance(et, str) and et.lower().strip() in _VALID_ETAPA:
        out["etapa_seguimiento"] = et.lower().strip()
    return out


async def extract(user_text: str, history: list[dict[str, str]] | None = None) -> dict[str, Any]:
    """Devuelve un dict con los campos detectados (solo los no nulos)."""
    if not user_text or not user_text.strip():
        return {}

    settings = get_settings()
    msgs: list[dict[str, str]] = [{"role": "system", "content": _SYSTEM}]
    if history:
        msgs.extend(history[-6:])
    msgs.append({"role": "user", "content": user_text})

    def _do() -> str:
        resp = _client().chat.completions.create(
            model=settings.openai_model_brain,
            messages=msgs,  # type: ignore[arg-type]
            temperature=0,
            max_tokens=200,
            response_format={"type": "json_object"},
        )
        return resp.choices[0].message.content or "{}"

    try:
        raw = await asyncio.to_thread(_do)
        data = json.loads(raw)
    except Exception as e:  # noqa: BLE001
        log.warning("extractor_failed", error=str(e))
        return {}

    if not isinstance(data, dict):
        return {}

    return _coerce(data)
