"""Parsea la respuesta del agente como un array JSON de mensajes consecutivos.

Reemplaza el "Code JSON Parser + Loop Over Items + Wait 1s" del flujo n8n.

Tolerancias:
- Si viene envuelto en triple backticks (```json ... ```), los quita.
- Si no es JSON válido, intenta recuperar:
  1. Envolver en `[...]` por si el modelo soltó solo los items separados por
     comas sin los corchetes.
  2. Dividir por línea en blanco y parsear cada bloque (caso típico: el
     modelo generó DOS arrays pegados).
  3. Como último recurso, extraer todas las cadenas entre comillas.
- Si nada funciona, devuelve el texto crudo como un único mensaje.
- Filtra strings vacíos.
"""

from __future__ import annotations

import json
import re

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)
_BLANK_LINES = re.compile(r"\n\s*\n+")
# Cadena JSON básica con soporte de escapes. Usado solo como último recurso.
_QUOTED = re.compile(r'"((?:[^"\\]|\\.)*)"', re.DOTALL)

MAX_MESSAGES = 4


def _coalesce(items: list[str], max_n: int) -> list[str]:
    """Fusiona los últimos items si exceden `max_n`, agrupando por bloques.

    Conserva los primeros `max_n - 1` mensajes y junta el resto en uno solo
    separado por saltos de línea.
    """
    if len(items) <= max_n:
        return items
    keep = items[: max_n - 1]
    tail = "\n".join(items[max_n - 1 :])
    return keep + [tail]


def _normalize(data: object) -> list[str]:
    """Aplana un valor parseado a una lista de strings no vacíos."""
    out: list[str] = []
    if isinstance(data, list):
        for item in data:
            if isinstance(item, str):
                t = item.strip()
                if t:
                    out.append(t)
            elif item is not None:
                out.append(json.dumps(item, ensure_ascii=False))
    elif isinstance(data, str):
        t = data.strip()
        if t:
            out.append(t)
    return out


def _try_recover(cleaned: str) -> list[str]:
    """Recupera chunks cuando el JSON viene roto.

    Casos comunes que arregla:
      a) `"a","b","c"`            (sin corchetes externos)
      b) `["a","b"]\n\n["c","d"]` (dos arrays pegados)
      c) basura con varias `"..."`
    """
    # (a) wrap simple
    try:
        d = json.loads("[" + cleaned + "]")
        items = _normalize(d)
        if items:
            return items
    except json.JSONDecodeError:
        pass

    # (b) split por línea en blanco y parsear cada bloque
    segments = [s.strip() for s in _BLANK_LINES.split(cleaned) if s.strip()]
    if len(segments) > 1:
        combined: list[str] = []
        ok = True
        for seg in segments:
            try:
                d = json.loads(seg if seg.startswith("[") else "[" + seg + "]")
                combined.extend(_normalize(d))
            except json.JSONDecodeError:
                ok = False
                break
        if ok and combined:
            return combined

    # (c) último recurso: jala todas las cadenas entre comillas
    matches = _QUOTED.findall(cleaned)
    items = [m.strip() for m in matches if m.strip()]
    if len(items) >= 1:
        return items
    return []


def split_response(raw: str) -> list[str]:
    if not raw:
        return []
    cleaned = _FENCE.sub("", raw.strip()).strip()

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        recovered = _try_recover(cleaned)
        if recovered:
            return _coalesce(recovered, MAX_MESSAGES)
        return [raw.strip()]

    items = _normalize(data)
    if not items:
        return [raw.strip()]
    return _coalesce(items, MAX_MESSAGES)
