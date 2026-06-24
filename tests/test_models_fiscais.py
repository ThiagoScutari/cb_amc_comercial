"""Testes das entidades fiscais/financeiras (S11): NotaFiscal, Titulo, Devolucao.

SQLite in-memory (fixtures `engine`/`session` do conftest, FK on). Escopo da fase:
schema + enums + relationships + CHECK. NÃO testa seed/tools/IDOR (fase futura).
"""

import datetime as dt
from decimal import Decimal

import pytest
from app.data.db import criar_engine, recriar_schema
from app.data.models import (
    Base,
    Cliente,
    Devolucao,
    NotaFiscal,
    Pedido,
    StatusDevolucao,
    StatusEntrega,
    StatusPedido,
    StatusTitulo,
    Titulo,
)
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

_HOJE = dt.date(2026, 6, 16)


def _grafo_minimo(session):
    """Cria cliente + pedido + NF + título + devolução mínimos e coerentes."""
    cliente = Cliente(
        razao_social="Loja Teste LTDA",
        nome_fantasia="Loja Teste",
        cnpj="12345678000199",
        telefone_whatsapp="5547999990000",
        contato_nome="Fulano",
        cidade_uf="Florianópolis/SC",
        condicao_pagamento="28/35/42 dias",
    )
    pedido = Pedido(
        id=9001,
        cliente=cliente,
        data_pedido=_HOJE,
        status=StatusPedido.faturado,
        valor_total=Decimal("1000.00"),
    )
    nf = NotaFiscal(
        id=7001,
        numero_nf=55001,
        cliente=cliente,
        pedido=pedido,
        data_emissao=_HOJE,
        chave_acesso="3" * 44,
        valor_total=Decimal("1000.00"),
        status_entrega=StatusEntrega.em_transito,
        transportadora="Correios",
        codigo_rastreio="BR123456789BR",
        data_prevista_entrega=_HOJE,
    )
    titulo = Titulo(
        numero_titulo="T-7001-1",
        cliente=cliente,
        nota_fiscal=nf,
        parcela="1/3",
        valor=Decimal("333.34"),
        data_vencimento=_HOJE,
        status=StatusTitulo.em_aberto,
        linha_digitavel="0" * 47,
    )
    devolucao = Devolucao(
        numero_devolucao="D-7001",
        cliente=cliente,
        nota_fiscal=nf,
        motivo="peça com defeito",
        status=StatusDevolucao.credito_gerado,
        valor_credito=Decimal("100.00"),
        data_credito=_HOJE,
        data_solicitacao=_HOJE,
    )
    session.add(cliente)
    session.flush()
    return cliente, pedido, nf, titulo, devolucao


# ---------- schema (recriar_schema cria as 3 tabelas) ----------
def test_recriar_schema_cria_tabelas_novas():
    eng = criar_engine("sqlite://")
    recriar_schema(eng)
    nomes = set(inspect(eng).get_table_names())
    assert {"notas_fiscais", "titulos", "devolucoes"} <= nomes
    # também presentes no metadata declarativo (fonte da verdade)
    assert {"notas_fiscais", "titulos", "devolucoes"} <= set(Base.metadata.tables)
    eng.dispose()


# ---------- persistência + relationships nos dois sentidos ----------
def test_persiste_e_relaciona_nos_dois_sentidos(session):
    cliente, _pedido, _nf, _titulo, _devolucao = _grafo_minimo(session)
    session.commit()
    session.expire_all()  # força recarga do banco (sem cache de identidade)

    nf = session.get(NotaFiscal, 7001)
    # filho -> pai
    assert nf.cliente.id == cliente.id
    assert nf.pedido.id == 9001
    # pai -> filhos (coleções da NF)
    assert [t.numero_titulo for t in nf.titulos] == ["T-7001-1"]
    assert [d.numero_devolucao for d in nf.devolucoes] == ["D-7001"]
    # título/devolução -> NF e cliente
    assert nf.titulos[0].nota_fiscal.id == 7001
    assert nf.titulos[0].cliente.id == cliente.id
    assert nf.devolucoes[0].nota_fiscal.id == 7001
    assert nf.devolucoes[0].cliente.id == cliente.id

    # cliente -> coleções inversas (back_populates novos)
    c = session.get(Cliente, cliente.id)
    assert [n.id for n in c.notas_fiscais] == [7001]
    assert [t.numero_titulo for t in c.titulos] == ["T-7001-1"]
    assert [d.numero_devolucao for d in c.devolucoes] == ["D-7001"]


# ---------- CHECK dos enums: só valores válidos ----------
@pytest.mark.parametrize(
    ("tabela", "coluna"),
    [
        ("notas_fiscais", "status_entrega"),
        ("titulos", "status"),
        ("devolucoes", "status"),
    ],
)
def test_check_enum_rejeita_valor_invalido(session, tabela, coluna):
    _grafo_minimo(session)
    session.commit()
    # O Enum(native_enum=False) gera VARCHAR + CHECK IN (...). Um valor fora do
    # conjunto é barrado pelo banco (bypass do ORM via SQL cru).
    with pytest.raises(IntegrityError):
        session.execute(text(f"UPDATE {tabela} SET {coluna} = '__INVALIDO__'"))  # noqa: S608
        session.flush()
    session.rollback()


def test_enum_valido_persiste_e_volta_como_enum(session):
    _grafo_minimo(session)
    session.commit()
    session.expire_all()
    nf = session.get(NotaFiscal, 7001)
    assert nf.status_entrega is StatusEntrega.em_transito  # round-trip do enum


# ---------- CHECK: valor_credito >= 0 quando não-nulo ----------
def test_check_valor_credito_negativo_e_barrado(session):
    cliente, _pedido, nf, _t, _d = _grafo_minimo(session)
    session.commit()
    ruim = Devolucao(
        numero_devolucao="D-NEG",
        cliente=cliente,
        nota_fiscal=nf,
        motivo="x",
        status=StatusDevolucao.solicitada,
        valor_credito=Decimal("-1.00"),
        data_solicitacao=_HOJE,
    )
    session.add(ruim)
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_valor_credito_nulo_e_zero_sao_validos(session):
    cliente, _pedido, nf, _t, _d = _grafo_minimo(session)
    session.commit()
    session.add_all(
        [
            Devolucao(
                numero_devolucao="D-NULL",
                cliente=cliente,
                nota_fiscal=nf,
                motivo="sem crédito ainda",
                status=StatusDevolucao.solicitada,
                valor_credito=None,
                data_solicitacao=_HOJE,
            ),
            Devolucao(
                numero_devolucao="D-ZERO",
                cliente=cliente,
                nota_fiscal=nf,
                motivo="crédito zero",
                status=StatusDevolucao.recebida,
                valor_credito=Decimal("0.00"),
                data_solicitacao=_HOJE,
            ),
        ]
    )
    session.flush()  # não levanta: NULL e 0 satisfazem o CHECK
    assert len(session.query(Devolucao).all()) == 3  # D-7001 + D-NULL + D-ZERO
