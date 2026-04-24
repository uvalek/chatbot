"""FastAPI: webhooks de Telegram y ManyChat."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import structlog
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from app import api as dashboard_api
from app import bot_settings, buffer, memory, test_mode
from app.channels import manychat as manychat_chan
from app.channels import telegram as telegram_chan
from app.config import get_settings
from app.graph import dispatch

settings = get_settings()
logging.basicConfig(level=settings.log_level)
# Silencia los INFO de httpx/httpcore (cada llamada a Supabase/OpenAI/ManyChat
# generaba 1-2 lineas que llenaban los logs sin aportar diagnostico). Solo
# warnings y errores de esas libs aparecen.
for noisy in ("httpx", "httpcore", "openai._base_client"):
    logging.getLogger(noisy).setLevel(logging.WARNING)
log = structlog.get_logger(__name__)

app = FastAPI(title="Chatbot Home Plus")

# CORS: permite al dashboard (Vercel + localhost dev) consumir /api/*
_origins = [o.strip() for o in settings.dashboard_cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_origin_regex=settings.dashboard_cors_origin_regex or None,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(dashboard_api.router)

# Conjunto de tasks vivos. Sin esta referencia fuerte el GC puede matar
# `asyncio.create_task(...)` a media ejecucion (gotcha conocido de Python).
_BG_TASKS: set[asyncio.Task] = set()


def _spawn(coro) -> asyncio.Task:
    task = asyncio.create_task(coro)
    _BG_TASKS.add(task)
    task.add_done_callback(_BG_TASKS.discard)
    return task


async def _reaper_loop() -> None:
    """Procesa mensajes huérfanos del buffer (cuando el contenedor reinicia
    mientras un `schedule_flush` dormía sus 25 s). Corre dentro del mismo
    proceso web para no depender de un segundo servicio en EasyPanel.
    """
    interval = max(10, settings.reaper_interval_seconds)
    log.info("reaper_start", interval=interval)
    tick = 0
    while True:
        try:
            n = await buffer.reap_orphans(dispatch)
            if n:
                log.info("reaper_processed", count=n)
        except Exception as e:  # noqa: BLE001
            log.exception("reaper_error", error=str(e))
        tick += 1
        if tick % 30 == 0:  # heartbeat cada ~30 min
            log.info("reaper_heartbeat", tick=tick)
        await asyncio.sleep(interval)


@app.on_event("startup")
async def _startup() -> None:
    # Pasada inmediata para limpiar lo que quedó en vuelo del contenedor anterior
    try:
        n = await buffer.reap_orphans(dispatch)
        if n:
            log.info("reaper_boot_processed", count=n)
    except Exception as e:  # noqa: BLE001
        log.exception("reaper_boot_error", error=str(e))
    _spawn(_reaper_loop())


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/admin/reap")
async def admin_reap(token: str | None = None) -> dict[str, object]:
    """Fuerza una pasada del reaper. Util para diagnostico cuando un mensaje
    queda atascado en buffer."""
    _check_token(token)
    n = await buffer.reap_orphans(dispatch)
    return {"processed": n, "bg_tasks": len(_BG_TASKS)}


@app.post("/webhook/telegram")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> dict[str, str]:
    if (
        settings.telegram_webhook_secret
        and x_telegram_bot_api_secret_token != settings.telegram_webhook_secret
    ):
        raise HTTPException(status_code=403, detail="invalid secret")

    update = await request.json()
    parsed = telegram_chan.parse_update(update)
    if not parsed:
        return {"status": "ignored"}

    media_url = None
    if parsed["media_file_id"]:
        try:
            media_url = await telegram_chan.resolve_file_url(parsed["media_file_id"])
        except Exception as e:  # noqa: BLE001
            log.warning("telegram_file_resolve_failed", error=str(e))

    # Toggle per-conversacion del dashboard: si el asesor apago el bot para
    # este chat, guardamos el mensaje en historial (para que aparezca en la UI)
    # pero no lo metemos al buffer ni disparamos al bot.
    if not await bot_settings.is_enabled(parsed["chat_id"]):
        await _store_user_message(parsed["chat_id"], parsed["text"], parsed["media_type"])
        return {"status": "queued_no_bot"}

    # Persiste canal + handle (telefono/@user/nombre) al primer mensaje.
    try:
        await bot_settings.ensure_row(parsed["chat_id"], "telegram")
        await _ensure_canal(parsed["chat_id"], "telegram", handle=parsed.get("handle"))
    except Exception as e:  # noqa: BLE001
        log.warning("telegram_persist_canal_failed", error=str(e), chat_id=parsed["chat_id"])

    await buffer.insert_message(
        chat_id=parsed["chat_id"],
        channel="telegram",
        payload=parsed["raw"],
        text=parsed["text"],
        media_type=parsed["media_type"],
        media_url=media_url,
    )
    _spawn(buffer.schedule_flush(parsed["chat_id"], "telegram", dispatch))
    return {"status": "queued"}


@app.api_route("/webhook/manychat", methods=["GET", "POST"])
async def manychat_webhook(request: Request) -> dict[str, str]:
    if settings.manychat_require_arm and not test_mode.is_armed_manychat():
        log.info("manychat_ignored_disarmed", method=request.method)
        return {"status": "disarmed"}

    if request.method == "GET":
        # ManyChat (plan básico) solo permite GET con query params
        body = dict(request.query_params)
        # Reconstruye estructura `last_interaction` si vienen mime/url
        if body.get("media_url") or body.get("mime_type"):
            body["last_interaction"] = {
                "url": body.get("media_url", ""),
                "mime_type": body.get("mime_type", ""),
            }
    else:
        try:
            body = await request.json()
        except Exception as e:  # noqa: BLE001
            log.warning("manychat_body_parse_failed", error=str(e))
            body = dict(request.query_params)

    log.info(
        "manychat_webhook_in",
        method=request.method,
        body_keys=list(body.keys()) if isinstance(body, dict) else None,
        body_preview={k: (str(v)[:80] if not isinstance(v, dict) else "<dict>") for k, v in (body.items() if isinstance(body, dict) else [])},
    )

    parsed = manychat_chan.parse_webhook(body)
    if not parsed:
        log.warning("manychat_parse_returned_none", body=body)
        return {"status": "ignored"}

    log.info(
        "manychat_parsed",
        chat_id=parsed["chat_id"],
        subchannel=parsed.get("subchannel"),
        has_text=bool(parsed.get("text")),
        media_type=parsed.get("media_type"),
    )

    # Toggle per-conversacion (ver telegram_webhook).
    if not await bot_settings.is_enabled(parsed["chat_id"]):
        log.info("manychat_queued_no_bot", chat_id=parsed["chat_id"])
        await _store_user_message(parsed["chat_id"], parsed["text"], parsed["media_type"])
        return {"status": "queued_no_bot"}

    # Persiste el sub-canal visible (whatsapp/instagram/messenger) en
    # bot_settings y contactos.canal para que el dashboard lo etiquete bien.
    # Tambien intenta resolver un "handle" identificable (telefono / nombre /
    # @ig_username) llamando a ManyChat getInfo. Best-effort: si falla, no
    # bloquea el flujo del bot.
    subchannel = parsed.get("subchannel") or "whatsapp"
    handle: str | None = None
    try:
        info = await manychat_chan.fetch_subscriber_info(parsed["chat_id"])
        if info:
            handle = manychat_chan.derive_handle(subchannel, info)
    except Exception as e:  # noqa: BLE001
        log.warning("manychat_fetch_info_failed", error=str(e), chat_id=parsed["chat_id"])
    try:
        await bot_settings.ensure_row(parsed["chat_id"], "manychat")
        await _ensure_canal(parsed["chat_id"], subchannel, handle=handle)
    except Exception as e:  # noqa: BLE001
        log.warning("manychat_persist_canal_failed", error=str(e), chat_id=parsed["chat_id"])

    # Inyectamos el subchannel en el payload del buffer para que el dispatch lo
    # recupere despues de la ventana (no podemos pasarlo por la firma, esa la
    # comparte con telegram).
    payload_with_sub = dict(parsed["raw"]) if isinstance(parsed["raw"], dict) else {}
    payload_with_sub["__subchannel"] = subchannel

    await buffer.insert_message(
        chat_id=parsed["chat_id"],
        channel="manychat",
        payload=payload_with_sub,
        text=parsed["text"],
        media_type=parsed["media_type"],
        media_url=parsed["media_url"],
    )
    _spawn(buffer.schedule_flush(parsed["chat_id"], "manychat", dispatch))
    test_mode.consume_manychat()
    return {"status": "queued"}


async def _ensure_canal(chat_id: str, canal: str, handle: str | None = None) -> None:
    """Asegura que la fila de `contactos` exista para esta conversacion.

    - `canal`: el webhook es la fuente de verdad (no es editable desde el CRM),
      asi que siempre se pisa con el ultimo valor recibido.
    - `handle`: identificador legible auto-detectado por canal (telefono WA,
      @ TG/IG, nombre FB). Solo se actualiza si la fila no lo tiene; el
      usuario podria haber dado luego un dato mejor (su nombre real va a `nombre`
      via el extractor M0).
    - NO toca `nombre` (lo gestiona el extractor o el asesor manualmente).
    """
    from app.db import supabase  # import local
    existing = await asyncio.to_thread(
        lambda: (
            supabase()
            .table("contactos")
            .select("id, canal, handle")
            .eq("chat_id", chat_id)
            .limit(1)
            .execute()
        )
    )
    rows = existing.data or []
    if not rows:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "canal": canal,
            "etapa_seguimiento": "nuevo",
        }
        if handle:
            payload["handle"] = handle
        # nombre arranca como NULL — el dashboard caera en handle como fallback.
        await asyncio.to_thread(
            lambda: supabase().table("contactos").insert(payload).execute()
        )
        return
    row = rows[0]
    update: dict[str, Any] = {}
    if row.get("canal") != canal:
        update["canal"] = canal
    if handle and not row.get("handle"):
        update["handle"] = handle
    if update:
        await asyncio.to_thread(
            lambda: (
                supabase()
                .table("contactos")
                .update(update)
                .eq("id", row["id"])
                .execute()
            )
        )


async def _store_user_message(chat_id: str, text: str | None, media_type: str | None) -> None:
    """Guarda un mensaje entrante en historial sin disparar al bot.
    Usado cuando el asesor apago el bot para esa conversacion."""
    content = text or ""
    if not content:
        if media_type == "audio":
            content = "[Audio recibido]"
        elif media_type == "image":
            content = "[Imagen recibida]"
        else:
            return
    try:
        await memory.append(chat_id, "user", content)
    except Exception as e:  # noqa: BLE001
        log.exception("store_user_msg_failed", chat_id=chat_id, error=str(e))


def _check_token(token: str | None) -> None:
    expected = settings.test_arm_token
    if not expected:
        raise HTTPException(status_code=503, detail="TEST_ARM_TOKEN no configurado")
    if token != expected:
        raise HTTPException(status_code=403, detail="invalid token")


@app.api_route("/test/manychat/arm", methods=["GET", "POST"])
async def manychat_arm(
    token: str | None = None,
    seconds: int = 600,
    one_shot: bool = True,
) -> dict[str, object]:
    _check_token(token)
    return test_mode.arm_manychat(seconds=seconds, one_shot=one_shot)


@app.api_route("/test/manychat/disarm", methods=["GET", "POST"])
async def manychat_disarm(token: str | None = None) -> dict[str, str]:
    _check_token(token)
    test_mode.disarm_manychat()
    return {"status": "disarmed"}


@app.get("/test/manychat/status")
async def manychat_status(token: str | None = None) -> dict[str, object]:
    _check_token(token)
    return test_mode.status_manychat()


# Panel HTML autosuficiente: un solo archivo, sin build, sin frontend separado.
# El token se guarda en localStorage del navegador; el server NUNCA lo loguea.
_PANEL_HTML = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Panel Bot WhatsApp</title>
<style>
  :root { color-scheme: light dark; }
  * { box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
    margin: 0; min-height: 100vh; display: grid; place-items: center;
    background: #0f172a; color: #e2e8f0; padding: 24px;
  }
  .card {
    background: #1e293b; border-radius: 16px; padding: 32px;
    width: 100%; max-width: 420px;
    box-shadow: 0 20px 60px rgba(0,0,0,.4);
  }
  h1 { margin: 0 0 4px; font-size: 22px; }
  .sub { color: #94a3b8; font-size: 13px; margin-bottom: 24px; }
  .status {
    display: flex; align-items: center; gap: 12px;
    padding: 16px; border-radius: 12px; margin-bottom: 20px;
    background: #0f172a; border: 1px solid #334155;
  }
  .dot { width: 14px; height: 14px; border-radius: 50%; background: #475569; transition: background .2s; }
  .dot.on { background: #22c55e; box-shadow: 0 0 12px #22c55e; }
  .status-text { font-weight: 600; }
  .meta { color: #94a3b8; font-size: 12px; margin-top: 2px; }
  button {
    width: 100%; padding: 16px; font-size: 16px; font-weight: 700;
    border: 0; border-radius: 12px; cursor: pointer;
    transition: transform .05s, opacity .15s;
    color: #fff;
  }
  button:active { transform: scale(.98); }
  button:disabled { opacity: .5; cursor: not-allowed; }
  .btn-on { background: #22c55e; }
  .btn-off { background: #ef4444; }
  label { display: block; font-size: 12px; color: #94a3b8; margin: 16px 0 6px; }
  input, select {
    width: 100%; padding: 10px 12px; border-radius: 8px;
    border: 1px solid #334155; background: #0f172a; color: #e2e8f0;
    font-size: 14px;
  }
  .row { display: flex; gap: 8px; }
  .row > * { flex: 1; }
  .msg { font-size: 12px; margin-top: 12px; min-height: 16px; }
  .msg.err { color: #f87171; }
  .msg.ok { color: #4ade80; }
  .footer { text-align: center; font-size: 11px; color: #64748b; margin-top: 18px; }
</style>
</head>
<body>
  <div class="card">
    <h1>Bot WhatsApp</h1>
    <div class="sub">Activa el bot solo cuando vayas a probarlo.</div>

    <div class="status">
      <div class="dot" id="dot"></div>
      <div>
        <div class="status-text" id="statusText">Cargando...</div>
        <div class="meta" id="meta"></div>
      </div>
    </div>

    <button id="toggle" disabled>—</button>

    <label for="token">Token</label>
    <input id="token" type="password" placeholder="TEST_ARM_TOKEN" autocomplete="off" />

    <div class="row">
      <div>
        <label for="seconds">Duración</label>
        <select id="seconds">
          <option value="300">5 min</option>
          <option value="600" selected>10 min</option>
          <option value="1800">30 min</option>
          <option value="3600">1 hora</option>
        </select>
      </div>
      <div>
        <label for="mode">Modo</label>
        <select id="mode">
          <option value="true" selected>Un mensaje</option>
          <option value="false">Ventana</option>
        </select>
      </div>
    </div>

    <div class="msg" id="msg"></div>
    <div class="footer">Estado se refresca cada 5 s</div>
  </div>

<script>
const $ = (id) => document.getElementById(id);
const tokenEl = $("token");
const btn = $("toggle");
const dot = $("dot");
const statusText = $("statusText");
const meta = $("meta");
const msg = $("msg");

tokenEl.value = localStorage.getItem("bot_token") || "";
tokenEl.addEventListener("input", () => localStorage.setItem("bot_token", tokenEl.value));

let state = { armed: false, remaining_seconds: 0, one_shot: true };

function render() {
  if (state.armed) {
    dot.classList.add("on");
    statusText.textContent = "ACTIVO";
    const m = Math.floor(state.remaining_seconds / 60);
    const s = state.remaining_seconds % 60;
    meta.textContent = `Modo: ${state.one_shot ? "un mensaje" : "ventana"} · ${m}m ${s}s restantes`;
    btn.textContent = "Desactivar bot";
    btn.className = "btn-off";
  } else {
    dot.classList.remove("on");
    statusText.textContent = "INACTIVO";
    meta.textContent = "El bot ignora todos los mensajes.";
    btn.textContent = "Activar bot";
    btn.className = "btn-on";
  }
  btn.disabled = !tokenEl.value;
}

async function call(path, params = {}) {
  const t = tokenEl.value.trim();
  if (!t) { showMsg("Falta token", true); return null; }
  const url = new URL(path, window.location.origin);
  url.searchParams.set("token", t);
  for (const [k, v] of Object.entries(params)) url.searchParams.set(k, v);
  try {
    const r = await fetch(url, { method: "POST" });
    if (!r.ok) {
      const txt = await r.text();
      showMsg(`Error ${r.status}: ${txt.slice(0, 120)}`, true);
      return null;
    }
    return await r.json();
  } catch (e) {
    showMsg("Error de red: " + e.message, true);
    return null;
  }
}

function showMsg(text, isErr = false) {
  msg.textContent = text;
  msg.className = "msg " + (isErr ? "err" : "ok");
  setTimeout(() => { msg.textContent = ""; msg.className = "msg"; }, 4000);
}

async function refresh() {
  const t = tokenEl.value.trim();
  if (!t) { btn.disabled = true; return; }
  const url = `/test/manychat/status?token=${encodeURIComponent(t)}`;
  try {
    const r = await fetch(url);
    if (!r.ok) return;
    state = await r.json();
    render();
  } catch (_) {}
}

btn.addEventListener("click", async () => {
  btn.disabled = true;
  if (state.armed) {
    const r = await call("/test/manychat/disarm");
    if (r) showMsg("Bot desactivado", false);
  } else {
    const r = await call("/test/manychat/arm", {
      seconds: $("seconds").value,
      one_shot: $("mode").value,
    });
    if (r) showMsg("Bot activado", false);
  }
  await refresh();
});

tokenEl.addEventListener("change", refresh);
refresh();
setInterval(refresh, 5000);
</script>
</body>
</html>
"""


@app.get("/panel", response_class=HTMLResponse)
async def panel() -> HTMLResponse:
    """Panel visual para activar/desactivar el bot. El token se guarda en
    localStorage del navegador; el server nunca lo loguea ni lo expone."""
    return HTMLResponse(_PANEL_HTML)
