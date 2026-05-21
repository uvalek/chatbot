"""Acortador de URLs para los canales que no soportan hipervínculos.

WhatsApp, Instagram y Messenger (vía ManyChat) solo mandan texto plano: no
se puede esconder un link detrás de una palabra. Para que los enlaces de
fotos no se vean como URLs larguísimas, los acortamos con is.gd (servicio
gratuito, sin API key).

Si is.gd falla o tarda, devolvemos la URL original (degradación elegante).
El resultado se cachea en memoria para no repetir llamadas por la misma URL.
"""

from __future__ import annotations

import httpx
import structlog

log = structlog.get_logger(__name__)

_IS_GD = "https://is.gd/create.php"
_cache: dict[str, str] = {}


async def shorten(url: str) -> str:
    """Devuelve una URL corta para `url`, o la original si el acortador falla."""
    if not url or not url.startswith("http"):
        return url
    cached = _cache.get(url)
    if cached:
        return cached
    try:
        async with httpx.AsyncClient(timeout=8) as http:
            r = await http.get(_IS_GD, params={"format": "simple", "url": url})
        short = r.text.strip()
        if r.status_code == 200 and short.startswith("http"):
            _cache[url] = short
            return short
        log.warning("shorten_failed", status=r.status_code, body=r.text[:120])
    except Exception as e:  # noqa: BLE001
        log.warning("shorten_exception", error=str(e))
    return url
