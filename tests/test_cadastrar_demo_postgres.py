"""Regressão em POSTGRES REAL: sequence de clientes após o seed (S10).

BUG TRAVADO AQUI: o seed insere clientes com id EXPLÍCITO (1..10), o que NÃO
move a sequence serial do Postgres. Sem realinhar a sequence, o primeiro insert
AUTO (scripts.cadastrar_demo -> Cliente sem id -> flush) tentaria id=1 e colidiria
com o seed (UniqueViolation em clientes_pkey).

Por que Postgres e não SQLite: o SQLite usa ROWID = max+1, então o bug NÃO
aparece lá (os testes SQLite passam mesmo sem o fix). A fidelidade da sequence
só existe no Postgres — por isso esta regressão roda via testcontainers (§A1),
reusando a fixture `pg_session` compartilhada em conftest.py.

Prova dos dois lados:
- test_cadastrar_apos_seed_nao_colide  -> COM o realinhamento (popular()): PASSA.
  É o trap: se alguém remover _sincronizar_sequence_clientes do seed, ele fica
  vermelho com IntegrityError (clientes_pkey).
- test_sequence_dessincronizada_colide -> recria a condição PRÉ-FIX (sequence em
  1) e prova que o cadastro colide. Documenta o mecanismo exato do bug.
"""

import pytest
from app.data.models import Cliente
from scripts.cadastrar_demo import cadastrar
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

pytestmark = pytest.mark.postgres

_SEQ_CLIENTES = "SELECT setval(pg_get_serial_sequence('clientes', 'id'), {arg})"
_REALINHAR = _SEQ_CLIENTES.format(arg="(SELECT MAX(id) FROM clientes)")


def test_cadastrar_apos_seed_nao_colide(pg_session):
    """seed -> cadastrar: o novo cliente recebe id AUTO acima do seed, sem colisão.

    Só passa porque popular() realinhou a sequence; é a regressão que trava o bug.
    """
    resumo = cadastrar(pg_session, "5547999998888", "Boutique do João")
    cliente = pg_session.scalar(select(Cliente).where(Cliente.telefone_whatsapp == "5547999998888"))
    assert resumo.acao == "criado"
    assert cliente is not None
    assert cliente.id >= 11  # acima dos ids fixos 1..10 do seed (sem colidir)
    pg_session.rollback()  # não polui o módulo (mesmo padrão dos writes de IDOR)


def test_segundo_cadastro_tambem_nao_colide(pg_session):
    """Dois cadastros distintos em sequência: ambos OK, ids distintos e >= 11."""
    r1 = cadastrar(pg_session, "5547999990001", "Loja Um")
    id1 = pg_session.scalar(select(Cliente.id).where(Cliente.telefone_whatsapp == "5547999990001"))
    r2 = cadastrar(pg_session, "5547999990002", "Loja Dois")
    id2 = pg_session.scalar(select(Cliente.id).where(Cliente.telefone_whatsapp == "5547999990002"))
    assert r1.acao == r2.acao == "criado"
    assert id1 >= 11 and id2 >= 11 and id1 != id2
    pg_session.rollback()


def test_sequence_dessincronizada_colide(pg_session):
    """Recria a condição PRÉ-FIX (sequence em 1) e prova que o cadastro colide.

    Documenta o mecanismo do bug: id=1 já é do seed -> UniqueViolation. Ao final
    restaura a sequence para não afetar os demais testes do módulo.
    """
    s = pg_session
    # nextval volta a 1 (id já ocupado pelo seed) — exatamente o estado sem o fix.
    s.execute(text(_SEQ_CLIENTES.format(arg="1, false")))
    with pytest.raises(IntegrityError) as exc:
        cadastrar(s, "5547900000009", "Loja Colisao")
    msg = str(exc.value).lower()
    assert "clientes_pkey" in msg or "unique" in msg
    s.rollback()
    # restaura a sequence (não-transacional) para os demais testes.
    s.execute(text(_REALINHAR))
    s.commit()
