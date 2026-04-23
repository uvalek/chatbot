"""Modo de prueba estilo n8n "Execute Workflow".

Mantiene un flag global en memoria que decide si el webhook de ManyChat procesa
o ignora los mensajes entrantes. Por default está DESARMADO (ignora todo) para
que el número productivo de WhatsApp no dispare al bot mientras atiendes
prospectos manualmente.

Para usarlo:
  1. POST /test/manychat/arm?token=...        → arma para el siguiente mensaje
  2. Mandas tú mismo un mensaje desde el canal de ManyChat
  3. El bot responde y se autodesarma (one-shot)
  4. Si pasan N segundos sin mensaje, también se desarma

Soporta también modo "ventana de tiempo" pasando ?one_shot=false&seconds=300.

NOTA: el estado vive en memoria; si reinicias el contenedor se desarma.
"""

from __future__ import annotations

import time
from threading import RLock

# RLock (reentrante) — `consume_manychat` adquiere el lock y llama a
# `disarm_manychat` que tambien lo adquiere. Con un Lock normal eso es
# deadlock que congela el event loop entero.
_lock = RLock()
_armed_until: float = 0.0
_one_shot: bool = True


def arm_manychat(seconds: int = 600, one_shot: bool = True) -> dict[str, object]:
    global _armed_until, _one_shot
    seconds = max(10, min(int(seconds), 3600))
    with _lock:
        _armed_until = time.time() + seconds
        _one_shot = bool(one_shot)
        return {
            "armed": True,
            "one_shot": _one_shot,
            "expires_in_seconds": seconds,
        }


def disarm_manychat() -> None:
    global _armed_until
    with _lock:
        _armed_until = 0.0


def is_armed_manychat() -> bool:
    return time.time() < _armed_until


def consume_manychat() -> None:
    """Llamar después de procesar un mensaje. Si está en one_shot, desarma."""
    with _lock:
        if _one_shot:
            disarm_manychat()


def status_manychat() -> dict[str, object]:
    remaining = max(0, int(_armed_until - time.time()))
    return {
        "armed": remaining > 0,
        "one_shot": _one_shot,
        "remaining_seconds": remaining,
    }
