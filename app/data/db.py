"""Engine e Session do banco, a partir das settings. Sem efeitos no import.

Introduzido na Fase 1c (item A5, antes adiado): o seed (e, na Fase 2, o
repository) precisam de um engine/sessão ligados ao Postgres via `DATABASE_URL`.
Os testes continuam usando SQLite in-memory (conftest), sem tocar aqui.
"""

from __future__ import annotations

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.data.models import Base


def criar_engine(database_url: str | None = None) -> Engine:
    url = database_url or get_settings().database_url
    return create_engine(url)


def criar_sessionmaker(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def recriar_schema(engine: Engine) -> None:
    """Recria o schema do zero (create_all, sem Alembic) — idempotente p/ o mock."""
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
