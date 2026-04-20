# Chatbot Home Plus — Python + LangGraph

Migración del chatbot inmobiliario de **n8n a Python**. Conserva el mismo flujo:

```
Webhook → buffer 25 s → resolver media → memoria → router → M1|M2|M3|M4 → split → enviar → guardar memoria
```

Cerebro: **gpt-4.1-mini** (router, M1, M2, M4) + **gpt-4o-mini** (M3 catálogo y visión) + **whisper-1** (audio).

## Arquitectura

| Capa | Archivo | Responsabilidad |
|---|---|---|
| Webhooks | `app/main.py` | FastAPI: `/webhook/telegram`, `/webhook/manychat` |
| Canales | `app/channels/telegram.py`, `app/channels/manychat.py` | Parseo entrante + envío saliente |
| Buffer | `app/buffer.py` | Acumula mensajes 25 s en `message_buffer` (Supabase) |
| Memoria | `app/memory.py` | Lee/guarda turnos en `chat_memory` (Supabase) |
| Media | `app/media.py` | Whisper (audio) + Vision gpt-4o-mini (imagen) |
| Router | `app/agents/router.py` | Clasifica → `M1|M2|M3|M4` |
| Agentes | `app/agents/m{1,2,3,4}_*.py` | FAQ + RAG / Agendamiento / Catálogo / Seguimiento |
| Tools | `app/tools/cal.py`, `hubspot.py`, `properties.py` | Cal.com v2, HubSpot, RPC `buscar_propiedades` |
| Splitter | `app/splitter.py` | Parte el JSON-array de respuesta en mensajes consecutivos |
| Grafo | `app/graph.py` | LangGraph que orquesta todo |
| Worker | `app/worker.py` | Recoge mensajes huérfanos del buffer si el web reinició |

## Setup local

```bash
# 1. Python 3.11+ y uv (o poetry / pip)
uv venv
source .venv/bin/activate
uv pip install -e ".[dev]"

# 2. Variables
cp .env.example .env
# completa OPENAI_API_KEY, SUPABASE_*, CAL_API_KEY, HUBSPOT_TOKEN, TELEGRAM_BOT_TOKEN, MANYCHAT_API_TOKEN

# 3. Migraciones en Supabase (en el SQL Editor del proyecto)
#    - supabase/migrations/001_message_buffer.sql
#    (RAG `documents` + `match_documents` y memoria `n8n_chat_histories`
#     ya existen del setup de n8n; no requieren migración nueva.)

# 4. Levantar dev server
uvicorn app.main:app --reload
```

Tests:

```bash
pytest -q
```

## Conectar el bot

### Telegram

```bash
curl "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/setWebhook?url=https://TU_DOMINIO/webhook/telegram&secret_token=$TELEGRAM_WEBHOOK_SECRET"
```

### ManyChat (WhatsApp)

En tu flujo de ManyChat agrega una *External Request* `POST` a `https://TU_DOMINIO/webhook/manychat` con el JSON del subscriber (incluye `id`, `text`, `last_interaction.url` y `last_interaction.mime_type` cuando aplique).

## Deploy en Railway

1. Conecta el repo, Railway detecta `pyproject.toml` con Nixpacks.
2. Define las env vars del `.env.example` en el dashboard.
3. Crea **dos** servicios desde el mismo repo, ambos usando `Procfile`:
   - `web`: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
   - `worker`: `python -m app.worker`
4. Apunta los webhooks al dominio público del servicio `web`.

## Mapeo n8n → Python (referencia rápida)

| Concepto n8n | Aquí |
|---|---|
| Telegram Trigger | `POST /webhook/telegram` (`app/main.py`) |
| Webhook genérico WhatsApp | `POST /webhook/manychat` (`app/main.py`) |
| Redis Insertar + Wait 25 s + Switch + Delete | `buffer.insert_message` + `buffer.schedule_flush` |
| Postgres Chat Memory (`n8n_chat_histories`) | `memory.load_history` / `memory.append` |
| OpenAI Whisper / Vision | `media.transcribe_audio` / `media.describe_image` |
| ROUTER | `agents/router.py` |
| M1 + Supabase Vector Store | `agents/m1_faq.py` (RPC `match_documents`) |
| M2 + subworkflows DISPONIBILIDAD/AGENDAMIENTO/REAGENDADOR | `agents/m2_agendamiento.py` + `tools/cal.py` + `tools/hubspot.py` |
| M3 HTTP Tool | `agents/m3_catalogo.py` + `tools/properties.py` |
| M4 | `agents/m4_seguimiento.py` |
| Code JSON Parser + Loop Over Items + Wait 1s | `splitter.split_response` + `channels/*.send_messages` |

## Migración por fases

1. Apunta el webhook de **un solo número de prueba** al servicio Python; el resto sigue en n8n.
2. Verifica paridad: FAQ, agendamiento real (con HubSpot + Cal.com), catálogo, audio, imagen.
3. Mueve el resto del tráfico y apaga los workflows de n8n.

## Notas

- El buffer usa `asyncio.create_task` + un `asyncio.Lock` por chat; si el contenedor se reinicia mid-sleep el `worker` reaplana mensajes pendientes con `created_at < now() - 25 s`.
- ManyChat outbound usa `sendContent` con `data.version: v2`. Si tu cuenta usa otro endpoint (Send Flow), ajusta `app/channels/manychat.py`.
- M1 espera que el RPC `match_documents` ya exista en Supabase (lo crea la extensión `pgvector` de tu setup actual).
