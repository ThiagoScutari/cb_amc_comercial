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
