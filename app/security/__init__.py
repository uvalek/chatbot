"""Capas de defensa de seguridad del chatbot.

Submódulos:
- `input_guard`: clasifica mensajes entrantes (SAFE / SUSPICIOUS / BLOCK).
- `output_guard`: sanea las respuestas del modelo antes de enviarlas.
- `prompt_fence`: envuelve el input del usuario para que el modelo lo trate
  como datos, no como instrucciones.
- `security_log`: log dedicado para eventos de seguridad.
- `token_budget`: control de gasto de tokens por chat (anti-abuso económico).
"""
