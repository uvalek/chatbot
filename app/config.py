from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openai_api_key: str
    openai_model_brain: str = "gpt-4.1-mini"
    openai_model_catalog: str = "gpt-4o-mini"
    openai_model_vision: str = "gpt-4o-mini"

    supabase_url: str
    supabase_service_key: str
    supabase_anon_key: str = ""
    supabase_rag_table: str = "documents"
    supabase_rag_query: str = "match_documents"
    supabase_properties_rpc: str = "buscar_propiedades"

    cal_api_key: str = ""
    cal_event_type_id: int = 0

    hubspot_token: str = ""

    telegram_bot_token: str = ""
    telegram_webhook_secret: str = ""

    manychat_api_token: str = ""

    buffer_window_seconds: int = 30
    # Intervalo del reaper de huerfanos (segundos). Es solo un respaldo
    # por si schedule_flush se muere; el flujo normal procesa en `buffer_window_seconds`.
    reaper_interval_seconds: int = 60
    memory_turns: int = 25
    send_delay_seconds: float = 1.0
    timezone: str = "America/Mexico_City"

    log_level: str = "INFO"

    # ManyChat test mode (estilo n8n "Execute Workflow")
    manychat_require_arm: bool = True
    test_arm_token: str = ""

    # Dashboard CRM externo (Vite/React en Vercel)
    # API key compartido (header X-API-Key) y origenes permitidos para CORS.
    # Acepta lista separada por comas: "https://a.com,https://b.vercel.app"
    dashboard_api_key: str = ""
    dashboard_cors_origins: str = (
        "https://luce-real-estate-landing.vercel.app,http://localhost:5173,http://localhost:3000"
    )
    # Por defecto sin regex (estaba aceptando *.vercel.app y eso permitia
    # a cualquiera deployar a Vercel y consumir el endpoint). Si se
    # necesita matchear varios subdominios, definir explicitamente con
    # la variable de entorno DASHBOARD_CORS_ORIGIN_REGEX.
    dashboard_cors_origin_regex: str = ""

    # --- Webchat (widget en alekagency.com) ----------------------------
    # Si se define, /api/webchat exige el header X-API-Key con este valor.
    # Asi el proxy de Next.js es el unico que puede llegar al endpoint.
    webchat_api_key: str = ""
    # Rate limit por IP (sliding window). 0 desactiva.
    webchat_rate_limit_per_min: int = 30
    # Limite de longitud del texto entrante (ya se truncaba a 2000;
    # ahora se rechaza el request si excede mucho).
    webchat_max_text_len: int = 2000
    # Origenes permitidos para el widget (CORS, header Origin).
    # Vacio = no se restringe por CORS (cualquier dominio puede hacer
    # cross-origin). Util para llamadas server-to-server, que es
    # exactamente nuestro caso (Next.js proxy).
    webchat_cors_origins: str = ""

    @property
    def prompts_dir(self) -> Path:
        return Path(__file__).parent / "prompts"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def load_prompt(name: str) -> str:
    return (get_settings().prompts_dir / f"{name}.md").read_text(encoding="utf-8")
