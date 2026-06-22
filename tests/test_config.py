"""Testes do carregamento de configuração (Pydantic Settings)."""

from app.config import Settings


def _settings() -> Settings:
    # _env_file=None: ignora qualquer .env do ambiente -> teste determinístico.
    return Settings(_env_file=None)


def test_defaults_quando_env_ausente(monkeypatch):
    for var in (
        "AGENT_MODEL",
        "ROUTER_MODEL",
        "APP_PORT",
        "LOG_LEVEL",
        "DATA_DIR",
        "EVOLUTION_INSTANCE",
    ):
        monkeypatch.delenv(var, raising=False)

    s = _settings()

    assert s.agent_model == "claude-sonnet-4-6"
    assert s.router_model == "claude-haiku-4-5-20251001"
    assert s.app_port == 8005
    assert s.log_level == "INFO"
    assert s.data_dir == "data"
    assert s.evolution_instance == "cb-amc-comercial"


def test_database_url_aponta_para_container_nao_localhost():
    # §13.1: host = nome do container, NUNCA localhost.
    s = _settings()
    assert "cb_amc_comercial_db" in s.database_url
    assert "localhost" not in s.database_url


def test_le_segredo_do_ambiente(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-123")
    s = _settings()
    assert s.anthropic_api_key == "sk-test-123"


def test_app_port_convertido_para_int(monkeypatch):
    monkeypatch.setenv("APP_PORT", "8005")
    s = _settings()
    assert isinstance(s.app_port, int)
    assert s.app_port == 8005


# --- regressão: formato de áudio OPUS p/ nota de voz (ptt) — hotfix do 400 no upload ---
def test_output_format_default_e_opus_para_ptt():
    # O default tem que ser OPUS (nota de voz). MP3 enviado como audio/ogg = 400 na Graph API.
    s = _settings()
    assert s.elevenlabs_output_format == "opus_48000_64"
    assert s.elevenlabs_output_format.startswith("opus_")


def test_env_var_sobrescreve_o_default_do_output_format(monkeypatch):
    # MECANISMO do bug: o valor do .env/ambiente VENCE o default do config. Por isso um .env
    # legado com mp3 derruba o ptt mesmo com o default opus -> cuidar do .env de produção.
    monkeypatch.setenv("ELEVENLABS_OUTPUT_FORMAT", "mp3_44100_128")
    assert _settings().elevenlabs_output_format == "mp3_44100_128"


def test_env_example_ship_opus_nao_mp3():
    # CAUSA-RAIZ: o template .env.example não pode pinar MP3 — o .env de produção é copiado
    # dele, e um mp3 ali sobrescreve o default opus e ressuscita o 400 no ptt.
    from pathlib import Path

    env_example = Path(__file__).resolve().parent.parent / ".env.example"
    linha = next(
        ln
        for ln in env_example.read_text(encoding="utf-8").splitlines()
        if ln.strip().startswith("ELEVENLABS_OUTPUT_FORMAT=")
    )
    valor = linha.split("=", 1)[1].split("#")[0].strip()
    assert valor.startswith("opus_"), f".env.example pina {valor!r}; deve ser OPUS p/ ptt"
