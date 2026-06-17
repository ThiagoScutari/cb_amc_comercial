"""Configuração central da aplicação (Pydantic Settings).

Padrão herdado do SheetTalk e estendido para este projeto: lê variáveis de
ambiente (e um `.env` opcional), com defaults seguros. Segredos têm default
vazio — nunca embutir chave no código (§15 nº7). O `DATABASE_URL` aponta para
o nome do container Postgres, nunca `localhost` (§13.1).
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Claude ---
    anthropic_api_key: str = ""
    agent_model: str = "claude-sonnet-4-6"
    router_model: str = "claude-haiku-4-5-20251001"

    # --- STT / TTS ---
    openai_api_key: str = ""  # Whisper (STT)
    elevenlabs_api_key: str = ""  # TTS — segredo, só no .env (gitignored)
    elevenlabs_voice_id: str = ""  # voz PT-BR escolhida
    # qualidade×latência configurável: eleven_flash_v2_5 (rápido) vs eleven_multilingual_v2
    elevenlabs_model: str = "eleven_flash_v2_5"
    elevenlabs_output_format: str = "mp3_44100_128"  # MP3 no fio; Evolution converte p/ ptt opus

    # --- WhatsApp (Evolution) ---
    evolution_api_url: str = ""
    evolution_api_key: str = ""
    evolution_instance: str = "cb-amc-comercial"

    # --- Banco (host = nome do container, NÃO localhost) ---
    database_url: str = "postgresql+psycopg://user:pass@cb_amc_comercial_db:5432/cb_amc_comercial"

    # --- App ---
    app_port: int = 8005  # porta de host reservada (PORT-REGISTRY)
    data_dir: str = "data"
    log_level: str = "INFO"


def get_settings() -> Settings:
    """Fábrica das settings (ponto único para injeção/override em testes)."""
    return Settings()
