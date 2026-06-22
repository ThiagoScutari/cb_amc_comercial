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
    # MP3 enviado como type:audio (audio/mpeg) na Cloud API — toca inline, NÃO é nota de
    # voz (ptt). A Cloud API não transcodifica (a Evolution transcodificava). Ver client.py:
    # ptt real exigiria OGG/OPUS aqui (polimento futuro).
    elevenlabs_output_format: str = "mp3_44100_128"

    # --- WhatsApp (Cloud API / Meta) ---
    whatsapp_waba_id: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_access_token: str = ""  # TODO: aguardando token permanente da Meta (System User)
    whatsapp_verify_token: str = ""  # string que VOCÊ define; usada na verificação do webhook
    whatsapp_app_secret: str = ""  # app secret p/ validar a assinatura do webhook (HMAC-SHA256)
    whatsapp_api_version: str = "v23.0"

    # --- WhatsApp (Evolution) — DEPRECADO: migrado p/ Cloud API; mantido p/ rollback ---
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
