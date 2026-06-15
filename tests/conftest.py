"""Fixtures base da suíte de testes.

Banco de teste da Fase 1 = SQLite in-memory (decisão A1=A): rápido, sem infra.
Usa StaticPool para que `create_all` e as sessões compartilhem a MESMA conexão
in-memory; habilita `PRAGMA foreign_keys=ON` para fidelidade de FK/constraints.

Nota (contrato A1/Fase 2): os testes de IDOR de fidelidade rodam contra Postgres
real, não SQLite.
"""

import pytest
from app.data.models import Base
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
