"""Router: clasifica el mensaje en M1 / M2 / M3 / M4."""

from __future__ import annotations

import asyncio
from typing import Literal

from openai import OpenAI

from app.config import get_settings, load_prompt

Route = Literal["M1", "M2", "M3", "M4"]
_VALID: set[str] = {"M1", "M2", "M3", "M4"}
_SYSTEM = load_prompt("router")


def _client() -> OpenAI:
    return OpenAI(api_key=get_settings().openai_api_key)


async def classify(user_text: str, history: list[dict[str, str]] | None = None) -> Route:
    settings = get_settings()
    msgs: list[dict[str, str]] = [{"role": "system", "content": _SYSTEM}]
    if history:
        msgs.extend(history[-10:])
    msgs.append({"role": "user", "content": user_text})

    def _do() -> str:
        resp = _client().chat.completions.create(
            model=settings.openai_model_brain,
            messages=msgs,  # type: ignore[arg-type]
            temperature=0,
            max_tokens=4,
        )
        return (resp.choices[0].message.content or "").strip().upper()

    raw = await asyncio.to_thread(_do)
    code = raw[:2] if raw else ""
    if code in _VALID:
        return code  # type: ignore[return-value]
    return "M3"
