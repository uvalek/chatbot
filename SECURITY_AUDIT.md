# Security Audit — Chatbot (Luce Real Estate / AlekAgency)

> Rama: `security/audit-fixes`
> Cambios mínimos, **sin tocar la lógica del chatbot**. Sólo hardening.

---

## Hallazgos y arreglos

### 🔴 ALTA — CORS permitía cualquier `*.vercel.app`

**Antes** (`app/config.py`):
```python
dashboard_cors_origin_regex: str = r"https://.*\.vercel\.app"
```

Cualquiera podía deployar a Vercel y consumir tu API. **Lo cambié a vacío
por defecto**. Si necesitas un regex para varios subdominios tuyos,
configúralo explícitamente vía env var `DASHBOARD_CORS_ORIGIN_REGEX`
apuntando *sólo* a tu dominio (ej. `^https://([a-z0-9-]+\.)?alekagency\.com$`).

### 🔴 ALTA — `/api/webchat` sin autenticación

El endpoint estaba abierto. Cualquiera con la URL podía abusar de tu cuota
de OpenAI mandando mensajes desde su propio script.

**Arreglo:** ahora acepta un header `X-API-Key` que debe coincidir con la
variable `WEBCHAT_API_KEY`. **Es opt-in** (si no defines la variable, el
endpoint sigue funcionando como antes, sin auth — así no rompo tu deploy
actual). Para activar la protección:

1. **En EasyPanel** (env vars del servicio chatbot):
   ```
   WEBCHAT_API_KEY=algo-largo-y-aleatorio
   ```
   Ejemplo: genera uno con `openssl rand -hex 32` o usa cualquier UUID.

2. **En Vercel** (env vars del sitio web):
   ```
   WEBCHAT_API_KEY=mismo-valor
   ```
   Y dile a Claude que actualice el proxy `/api/chat` en el repo
   `agencyweb2.0` para que lo envíe en el header. Sólo tarda 30 segundos.

Mientras no actives la variable en EasyPanel, todo sigue igual.

### 🟠 MEDIA — `/api/webchat` sin rate limit

Cualquier IP podía mandar peticiones infinitas. Añadí limitador in-memory
**30 mensajes / minuto / IP** (variable `WEBCHAT_RATE_LIMIT_PER_MIN`,
poner `0` desactiva). Es ventana deslizante por IP y honra
`X-Forwarded-For` para funcionar detrás del proxy de EasyPanel.

### 🟠 MEDIA — Sin security headers en respuestas

Todas las respuestas ahora llevan:
```
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Referrer-Policy: strict-origin-when-cross-origin
Permissions-Policy: camera=(), microphone=(), geolocation=()
```

No agrego CSP global a propósito: el `/panel` usa scripts inline y
romper eso afectaría tu operación. Si en el futuro necesitas CSP,
hablamos.

### 🟡 BAJA — Container corría como root

`Dockerfile` ahora crea un usuario `chatbot` (uid 1001) y hace `USER chatbot`
antes del `CMD`. Si alguien lograra explotar el proceso, no llega a root.

### 🟡 BAJA — Truncado silencioso de mensajes largos

Antes, mensajes >2000 chars se truncaban silenciosamente. Ahora devuelve
HTTP `413 text_too_long` y el cliente sabe que su mensaje fue rechazado.

---

## Cambios por archivo

- `app/config.py` — nuevas variables (`webchat_api_key`,
  `webchat_rate_limit_per_min`, `webchat_max_text_len`,
  `webchat_cors_origins`); `dashboard_cors_origin_regex` por defecto
  vacío.
- `app/main.py` — middleware `SecurityHeadersMiddleware`, guard de
  webchat (`_require_webchat_key`), rate limit en `/api/webchat`,
  rechazo explícito de textos largos.
- `app/rate_limit.py` — limitador en memoria (nuevo).
- `Dockerfile` — usuario `chatbot` no-root.

---

## Acciones manuales tuyas (EasyPanel)

1. **Agrega `WEBCHAT_API_KEY`** en las env vars del servicio del chatbot
   en EasyPanel.

2. **Quita el regex permisivo** si lo tenías en `DASHBOARD_CORS_ORIGIN_REGEX`.
   La rama lo elimina por defecto. Si tu dashboard real estaba apuntando
   a `*.vercel.app`, define en su lugar el regex específico de tu dominio
   (ej. `^https://luce-real-estate-landing\.vercel\.app$`).

3. **Redeploya** desde EasyPanel.

4. Después, pídele a Claude (en el repo `agencyweb2.0`) que añada el
   `WEBCHAT_API_KEY` al proxy `/api/chat`. Una vez hecho ambos lados,
   nadie externo puede tocar tu endpoint sin saber la key.

## Lo que NO toqué (y por qué)

- **Toda la lógica del chatbot**: prompts, agentes, LangGraph, dispatch,
  buffers — nada. Solo añadí guardias antes y después.
- **`/api/telegram` y `/api/manychat`**: ya tienen sus propios mecanismos
  (`telegram_webhook_secret`, `manychat_require_arm`); no quise meterme
  ahí sin contexto operacional.
- **Tests existentes**: no toqué los `tests/` para no inducir cambios
  ocultos. Si quieres puedo añadir tests para el rate limit y el guard.
