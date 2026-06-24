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
    # OGG/OPUS para nota de voz (ptt) na Cloud API; mono. O WhatsApp só renderiza a resposta
    # como nota de voz (bolinha de microfone) quando o áudio é OGG/OPUS — é o FORMATO que
    # decide, não um campo no payload (não existe voice:true na Cloud API). 48kHz/64kbps:
    # equilíbrio p/ voz; ElevenLabs TTS é mono por natureza. Sobreponível por env
    # (ELEVENLABS_OUTPUT_FORMAT). Valores OPUS válidos no SDK: opus_48000_{32,64,96,128,192}.
    elevenlabs_output_format: str = "opus_48000_64"

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

    # --- Telefones dos clientes-demo do seed (S17a) ---
    # Reais na VPS via .env; defaults FICTÍCIOS determinísticos p/ dev/CI. NÃO setar em
    # dev/CI: os testes assumem estes defaults (o seed lê estes campos em runtime).
    demo_phone_1: str = "5531999990001"  # cliente 1 (Boutique Aurora) — era seed.DEMO_PHONE
    demo_phone_2: str = "5531988880002"  # cliente 2 (Maré Alta) — alvo do IDOR
    demo_phone_3: str = "5511977770003"  # cliente 3 (Debora Modas)

    # --- Banco (host = nome do container, NÃO localhost) ---
    database_url: str = "postgresql+psycopg://user:pass@cb_amc_comercial_db:5432/cb_amc_comercial"

    # --- App ---
    app_port: int = 8005  # porta de host reservada (PORT-REGISTRY)
    data_dir: str = "data"
    log_level: str = "INFO"


def get_settings() -> Settings:
    """Fábrica das settings (ponto único para injeção/override em testes)."""
    return Settings()
