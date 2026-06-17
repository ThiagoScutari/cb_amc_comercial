"""Fixtures base da suíte de testes.

Banco de teste da Fase 1 = SQLite in-memory (decisão A1=A): rápido, sem infra.
Usa StaticPool para que `create_all` e as sessões compartilhem a MESMA conexão
in-memory; habilita `PRAGMA foreign_keys=ON` para fidelidade de FK/constraints.

Nota (contrato A1/Fase 2): os testes de IDOR de fidelidade rodam contra Postgres
real, não SQLite. A fixture `pg_session` (Postgres efêmero via testcontainers,
seed real) é COMPARTILHADA aqui porque há >1 consumidor: os testes de IDOR
(test_idor_postgres.py) e o teste de regressão da sequence (S10).
"""

import pytest
from app.data.db import recriar_schema
from app.data.models import Base
from app.data.seed import popular
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture
def engine():
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(eng, "connect")
    def _fk_pragma(dbapi_con, _record):
        dbapi_con.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture
def session(engine) -> Session:
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as s:
        yield s


@pytest.fixture(scope="module")
def pg_session():
    """Postgres efêmero (testcontainers), schema recriado + seed real, 1 por módulo.

    Mesma fidelidade do banco de produção (sequence, constraints) — os testes de
    IDOR e de regressão da sequence precisam do Postgres, não do SQLite. Skipa
    limpo se testcontainers/Docker não estiverem disponíveis.
    """
    try:
        from testcontainers.postgres import PostgresContainer
    except ImportError:  # pragma: no cover
        pytest.skip("testcontainers não instalado")
    try:
        container = PostgresContainer("postgres:15", driver="psycopg")
        container.start()
    except Exception as exc:  # pragma: no cover - Docker ausente
        pytest.skip(f"Docker indisponível: {exc}")
    try:
        engine = create_engine(container.get_connection_url())
        recriar_schema(engine)
        with Session(engine) as s:
            popular(s)
            s.commit()
        with Session(engine) as s:
            yield s
        engine.dispose()
    finally:
        container.stop()
