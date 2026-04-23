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
    dashboard_cors_origin_regex: str = r"https://.*\.vercel\.app"

    @property
    def prompts_dir(self) -> Path:
        return Path(__file__).parent / "prompts"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def load_prompt(name: str) -> str:
    return (get_settings().prompts_dir / f"{name}.md").read_text(encoding="utf-8")
