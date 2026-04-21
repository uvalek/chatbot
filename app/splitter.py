"""Parsea la respuesta del agente como un array JSON de mensajes consecutivos.

Reemplaza el "Code JSON Parser + Loop Over Items + Wait 1s" del flujo n8n.

Tolerancias:
- Si viene envuelto en triple backticks (```json ... ```), los quita.
- Si no es JSON válido, devuelve el texto original como un único mensaje.
- Filtra strings vacíos.
"""

from __future__ import annotations

import json
import re

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)

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


def split_response(raw: str) -> list[str]:
    if not raw:
        return []
    cleaned = _FENCE.sub("", raw.strip()).strip()

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        return [raw.strip()]

    if isinstance(data, list):
        out: list[str] = []
        for item in data:
            if isinstance(item, str):
                t = item.strip()
                if t:
                    out.append(t)
            elif item is not None:
                out.append(json.dumps(item, ensure_ascii=False))
        if not out:
            return [raw.strip()]
        return _coalesce(out, MAX_MESSAGES)

    if isinstance(data, str):
        return [data.strip()] if data.strip() else []

    return [raw.strip()]
