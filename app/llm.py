"""Compatibilidad de parámetros entre modelos clásicos y de razonamiento.

Los modelos de la familia GPT-5 / o-series ("razonamiento") cambian la API
respecto a los clásicos (gpt-4.1, gpt-4o):

- NO aceptan `temperature` distinta del default (1). Si la mandas, la API
  responde 400. Por eso aquí la omitimos para esos modelos.
- Usan `max_completion_tokens` en lugar de `max_tokens`. Además gastan tokens
  internos "pensando", así que un techo muy bajo (ej. el router con 4) haría
  que la respuesta visible salga vacía. Subimos el techo a un piso seguro.
- Aceptan `reasoning_effort` ("minimal" | "low" | "medium" | "high").

`completion_params(model, ...)` arma el diccionario de kwargs correcto según
el modelo, para que se pueda alternar entre gpt-4.1 y gpt-5.4-nano cambiando
SOLO la variable de entorno, sin tocar el código.
"""

from __future__ import annotations

from app.config import get_settings

# Prefijos de modelos que razonan (consumen tokens internos, sin temperature).
_REASONING_PREFIXES = ("gpt-5", "o1", "o3", "o4")


def is_reasoning_model(model: str | None) -> bool:
    return (model or "").lower().startswith(_REASONING_PREFIXES)


def completion_params(
    model: str,
    *,
    temperature: float | None = None,
    max_tokens: int | None = None,
    reasoning_effort: str | None = None,
) -> dict:
    """Devuelve los kwargs compatibles con `chat.completions.create` para `model`.

    Para modelos de razonamiento: omite `temperature`, traduce `max_tokens` a
    `max_completion_tokens` (con un piso seguro) y agrega `reasoning_effort`.
    Para modelos clásicos: pasa `temperature` y `max_tokens` tal cual.
    """
    s = get_settings()
    params: dict = {}
    if is_reasoning_model(model):
        effort = reasoning_effort or s.openai_reasoning_effort
        if effort:
            params["reasoning_effort"] = effort
        if max_tokens is not None:
            params["max_completion_tokens"] = max(
                max_tokens, s.openai_reasoning_max_tokens_floor
            )
    else:
        if temperature is not None:
            params["temperature"] = temperature
        if max_tokens is not None:
            params["max_tokens"] = max_tokens
    return params
