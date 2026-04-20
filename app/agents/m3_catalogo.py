"""M3 — Catálogo de propiedades. Llama tool `buscar_propiedades` (Supabase RPC)."""

from __future__ import annotations

import asyncio
import json

from openai import OpenAI

from app.config import get_settings, load_prompt
from app.tools.properties import buscar_propiedades

_SYSTEM = load_prompt("m3_catalogo")

_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "buscar_propiedades",
            "description": (
                "Busca propiedades en el catálogo Home Plus. "
                "Acepta un único parámetro 'busqueda' con palabras clave."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "busqueda": {
                        "type": "string",
                        "description": "Palabras clave del usuario (zona, tipo, nombre).",
                    }
                },
                "required": ["busqueda"],
            },
        },
    }
]


def _client() -> OpenAI:
    return OpenAI(api_key=get_settings().openai_api_key)


async def respond(user_text: str, history: list[dict[str, str]]) -> str:
    s = get_settings()
    msgs: list[dict] = [{"role": "system", "content": _SYSTEM}]
    msgs.extend(history[-15:])
    msgs.append({"role": "user", "content": user_text})

    for _ in range(4):  # máximo 4 vueltas de tool calling
        def _call() -> dict:
            resp = _client().chat.completions.create(
                model=s.openai_model_catalog,
                messages=msgs,  # type: ignore[arg-type]
                tools=_TOOLS,  # type: ignore[arg-type]
                temperature=0.1,
            )
            return resp.choices[0].message.model_dump()

        choice = await asyncio.to_thread(_call)
        msgs.append(choice)
        tool_calls = choice.get("tool_calls") or []
        if not tool_calls:
            return choice.get("content") or ""

        for tc in tool_calls:
            args = json.loads(tc["function"]["arguments"] or "{}")
            results = await buscar_propiedades(args.get("busqueda", ""))
            msgs.append(
                {
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": json.dumps(results, ensure_ascii=False),
                }
            )

    return ""
