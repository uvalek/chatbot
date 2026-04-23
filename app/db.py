"""Cliente Supabase con HTTP/1.1 forzado.

Supabase (PostgREST detras de Cloudflare) cierra conexiones HTTP/2 ociosas
sin avisar. supabase-py reusa el pool y la siguiente request peta con
`httpx.RemoteProtocolError: Server disconnected`. Forzar HTTP/1.1 + keepalive
corto evita el problema.
"""

from __future__ import annotations

from functools import lru_cache

import httpx
import structlog
from supabase import Client, create_client

from app.config import get_settings

log = structlog.get_logger(__name__)


def _harden_httpx_clients(client: Client) -> None:
    """Reemplaza el httpx.Client interno de postgrest/storage/auth por uno sin
    HTTP/2 y con keep-alive corto. Hace best-effort: si la version de
    supabase-py no expone el atributo esperado, lo deja como esta."""
    targets = []
    pg = getattr(client, "postgrest", None)
    if pg is not None:
        targets.append(pg)
    for sub in targets:
        for attr in ("session", "_client"):
            sess = getattr(sub, attr, None)
            if isinstance(sess, httpx.Client):
                try:
                    new = httpx.Client(
                        base_url=str(sess.base_url),
                        headers=dict(sess.headers),
                        timeout=sess.timeout,
                        http2=False,
                        limits=httpx.Limits(
                            max_keepalive_connections=5,
                            keepalive_expiry=15.0,
                        ),
                    )
                    try:
                        sess.close()
                    except Exception:  # noqa: BLE001
                        pass
                    setattr(sub, attr, new)
                    log.info("supabase_httpx_hardened", target=type(sub).__name__, attr=attr)
                except Exception as e:  # noqa: BLE001
                    log.warning("supabase_httpx_harden_failed", error=str(e))
                break


@lru_cache
def supabase() -> Client:
    s = get_settings()
    client = create_client(s.supabase_url, s.supabase_service_key)
    _harden_httpx_clients(client)
    return client
