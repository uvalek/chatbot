"""M4 — Seguimiento de leads que ya tuvieron contacto."""

from __future__ import annotations

import asyncio

from openai import OpenAI

from app.config import get_settings, load_prompt

_SYSTEM = load_prompt("m4_seguimiento")


def _client() -> OpenAI:
    return OpenAI(api_key=get_settings().openai_api_key)


async def respond(user_text: str, history: list[dict[str, str]]) -> str:
    s = get_settings()
    msgs: list[dict[str, str]] = [{"role": "system", "content": _SYSTEM}]
    msgs.extend(history[-25:])
    msgs.append({"role": "user", "content": user_text})

    def _do() -> str:
        resp = _client().chat.completions.create(
            model=s.openai_model_brain,
            messages=msgs,  # type: ignore[arg-type]
            temperature=0.5,
        )
        return resp.choices[0].message.content or ""

    return await asyncio.to_thread(_do)
