"""FastAPI: webhooks de Telegram y ManyChat."""

from __future__ import annotations

import asyncio
import logging

import structlog
from fastapi import FastAPI, Header, HTTPException, Request

from app import buffer, test_mode
from app.channels import manychat as manychat_chan
from app.channels import telegram as telegram_chan
from app.config import get_settings
from app.graph import dispatch

settings = get_settings()
logging.basicConfig(level=settings.log_level)
log = structlog.get_logger(__name__)

app = FastAPI(title="Chatbot Home Plus")


async def _reaper_loop() -> None:
    """Procesa mensajes huérfanos del buffer (cuando el contenedor reinicia
    mientras un `schedule_flush` dormía sus 25 s). Corre dentro del mismo
    proceso web para no depender de un segundo servicio en EasyPanel.
    """
    interval = max(5, settings.buffer_window_seconds // 2)
    log.info("reaper_start", interval=interval)
    while True:
        try:
            n = await buffer.reap_orphans(dispatch)
            if n:
                log.info("reaper_processed", count=n)
        except Exception as e:  # noqa: BLE001
            log.exception("reaper_error", error=str(e))
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
    asyncio.create_task(_reaper_loop())


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


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

    await buffer.insert_message(
        chat_id=parsed["chat_id"],
        channel="telegram",
        payload=parsed["raw"],
        text=parsed["text"],
        media_type=parsed["media_type"],
        media_url=media_url,
    )
    asyncio.create_task(buffer.schedule_flush(parsed["chat_id"], "telegram", dispatch))
    return {"status": "queued"}


@app.api_route("/webhook/manychat", methods=["GET", "POST"])
async def manychat_webhook(request: Request) -> dict[str, str]:
    if settings.manychat_require_arm and not test_mode.is_armed_manychat():
        log.info("manychat_ignored_disarmed")
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
        except Exception:
            body = dict(request.query_params)

    parsed = manychat_chan.parse_webhook(body)
    if not parsed:
        return {"status": "ignored"}

    await buffer.insert_message(
        chat_id=parsed["chat_id"],
        channel="manychat",
        payload=parsed["raw"],
        text=parsed["text"],
        media_type=parsed["media_type"],
        media_url=parsed["media_url"],
    )
    asyncio.create_task(buffer.schedule_flush(parsed["chat_id"], "manychat", dispatch))
    test_mode.consume_manychat()
    return {"status": "queued"}


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
