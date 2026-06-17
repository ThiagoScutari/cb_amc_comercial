"""Fixtures das EVALS DE COMPORTAMENTO — batem na Claude API REAL (custo, lento).

NÃO rodam no CI: o `addopts` tem `-m "not eval"`. Rodar sob demanda com
`pytest -m eval` e `ANTHROPIC_API_KEY` no .env. Sem a key, os testes SKIPAM (em vez
de falhar), p/ um `pytest -m eval` acidental não quebrar.

O banco é SQLite in-memory com o seed REAL (determinístico): pedido 4471, camiseta
branca M, etc. A não-determinismo do MODELO é tratada nos próprios testes (N rodadas
+ limiar por severidade — ver test_evals.py).
"""

from __future__ import annotations

import pytest
from app.agent.orchestrator import HistoricoMemoria, Orquestrador
from app.config import get_settings
from app.data.models import Base
from app.data.repository import MockRepository
from app.data.seed import popular
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture(scope="session")
def _api_key() -> str:
    key = get_settings().anthropic_api_key
    if not key:
        pytest.skip("ANTHROPIC_API_KEY ausente — evals reais não rodam (rode no host).")
    return key


@pytest.fixture(scope="session")
def cliente_real(_api_key):
    """Client AsyncAnthropic REAL (key só de settings)."""
    from anthropic import AsyncAnthropic

    return AsyncAnthropic(api_key=_api_key)


@pytest.fixture(scope="module")
def repo():
    """Repositório sobre SQLite in-memory com o seed real."""
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    sm = sessionmaker(bind=engine, expire_on_commit=False)
    with sm() as s:
        popular(s)
        s.commit()
    with sm() as s:
        yield MockRepository(s)
    engine.dispose()


@pytest.fixture
def novo_orquestrador(cliente_real):
    """Fábrica de Orquestrador com histórico LIMPO (cada rodada de eval é independente)."""

    def _novo() -> Orquestrador:
        return Orquestrador(cliente_real, HistoricoMemoria(), get_settings().agent_model)

    return _novo
