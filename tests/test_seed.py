"""Testes do seed (coerência, demo, idempotência). SQLite in-memory, sem rede."""

from collections import defaultdict
from decimal import Decimal

import pytest
from app.data.catalogo import carregar_produtos
from app.data.db import criar_engine, recriar_schema
from app.data.models import (
    STATUS_FATURADOS,
    Cliente,
    Estoque,
    Pedido,
    PedidoItem,
    Produto,
    Solicitacao,
    StatusPedido,
    StatusSolicitacao,
)
from app.data.seed import DEMO_CLIENTE_ID, popular
from sqlalchemy import select
from sqlalchemy.orm import Session


@pytest.fixture
def db(session) -> Session:
    popular(session)
    session.flush()
    return session


# ---------- contagens ----------
def test_contagens(db):
    assert len(db.scalars(select(Cliente)).all()) == 10
    assert len(db.scalars(select(Produto)).all()) == len(carregar_produtos())
    assert len(db.scalars(select(Pedido)).all()) >= 9


# ---------- valor_total = soma dos itens ----------
def test_valor_total_soma_dos_itens(db):
    itens_por_pedido: dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
    for it in db.scalars(select(PedidoItem)).all():
        itens_por_pedido[it.pedido_id] += it.quantidade * it.preco_unitario
    for ped in db.scalars(select(Pedido)).all():
        assert ped.valor_total == itens_por_pedido[ped.id]


# ---------- estoque coerente com Q2 ----------
def test_estoque_coerente_reservado_disponivel(db):
    ped_by_id = {p.id: p for p in db.scalars(select(Pedido)).all()}
    res: dict[int, int] = defaultdict(int)
    disp: dict[int, int] = defaultdict(int)
    for it in db.scalars(select(PedidoItem)).all():
        st = ped_by_id[it.pedido_id].status
        if st in STATUS_FATURADOS:
            res[it.sku_id] += it.quantidade
        elif st != StatusPedido.cancelado:  # não-faturado e não-cancelado
            disp[it.sku_id] += it.quantidade
    for e in db.scalars(select(Estoque)).all():
        assert e.reservado == res[e.sku_id]
        assert e.disponivel == disp[e.sku_id]
        assert e.saldo >= 0 and e.disponivel >= 0 and e.reservado >= 0


def test_cancelado_nao_conta_no_estoque(db):
    cancelados = {
        p.id for p in db.scalars(select(Pedido)).all() if p.status == StatusPedido.cancelado
    }
    qtd_cancelada = sum(
        it.quantidade for it in db.scalars(select(PedidoItem)).all() if it.pedido_id in cancelados
    )
    qtd_nao_cancelada = sum(
        it.quantidade
        for it in db.scalars(select(PedidoItem)).all()
        if it.pedido_id not in cancelados
    )
    total_comprometido = sum(e.reservado + e.disponivel for e in db.scalars(select(Estoque)).all())
    assert qtd_cancelada > 0  # há ao menos um pedido cancelado (caso faturado->cancelado)
    assert total_comprometido == qtd_nao_cancelada  # itens cancelados NÃO entram


# ---------- integridade referencial ----------
def test_integridade_referencial(db):
    cli_ids = {c.id for c in db.scalars(select(Cliente)).all()}
    prod_ids = {p.id for p in db.scalars(select(Produto)).all()}
    ped_ids = {p.id for p in db.scalars(select(Pedido)).all()}
    for p in db.scalars(select(Pedido)).all():
        assert p.cliente_id in cli_ids
    for it in db.scalars(select(PedidoItem)).all():
        assert it.pedido_id in ped_ids
        assert it.sku_id in prod_ids
    for s in db.scalars(select(Solicitacao)).all():
        assert s.cliente_id in cli_ids


# ---------- demo: §10 ----------
def test_pedido_4471_existe_e_cancelavel(db):
    p = db.get(Pedido, 4471)
    assert p is not None
    assert p.cliente_id == DEMO_CLIENTE_ID
    assert p.faturado is False  # não-faturado -> cancelável ("quero cancelar o 4471")
    assert len(p.itens) >= 1


def test_camiseta_demo_e_compravel(db):
    prod = db.scalars(select(Produto).where(Produto.sku == "340103413-M")).one()
    est = db.get(Estoque, prod.id)
    assert est.saldo > 0  # "tem camiseta ... M pra comprar?" -> saldo>0


def test_todos_os_status_cobertos_no_cliente_demo(db):
    status = {
        p.status
        for p in db.scalars(select(Pedido).where(Pedido.cliente_id == DEMO_CLIENTE_ID)).all()
    }
    assert status == set(StatusPedido)


def test_solicitacao_pendente_pertence_ao_cliente(db):
    sols = [
        s for s in db.scalars(select(Solicitacao)).all() if s.status == StatusSolicitacao.pendente
    ]
    assert len(sols) >= 1
    for s in sols:
        if s.pedido_id is not None:  # anti-IDOR no caminho de escrita (contrato Fase 5)
            assert db.get(Pedido, s.pedido_id).cliente_id == s.cliente_id


def test_distribuicao_de_saldo_para_demo(db):
    saldos = [e.saldo for e in db.scalars(select(Estoque)).all()]
    assert any(s == 0 for s in saldos)  # sold-out
    assert any(0 < s <= 3 for s in saldos)  # estoque baixo (urgência)
    assert any(s >= 15 for s in saldos)  # confortável


def test_condicao_pagamento_preenchida(db):
    for c in db.scalars(select(Cliente)).all():
        assert c.condicao_pagamento  # "qual minha condição de pagamento?"


# ---------- sanidade gênero x tipo_cod ----------
def test_genero_coerente_com_tipo_cod(db):
    # tipo_cod codifica peça+gênero: último dígito ímpar=Masculino, par=Feminino.
    for p in db.scalars(select(Produto)).all():
        if p.tipo_cod is None:
            continue
        esperado_masc = int(p.tipo_cod) % 2 == 1
        assert (p.genero == "Masculino") == esperado_masc


# ---------- idempotência / determinismo ----------
def test_determinismo_entre_execucoes():
    resultados = []
    for _ in range(2):
        eng = criar_engine("sqlite://")
        recriar_schema(eng)
        with Session(eng) as s:
            popular(s)
            s.commit()
            resultados.append(
                (
                    len(s.scalars(select(Cliente)).all()),
                    len(s.scalars(select(Pedido)).all()),
                    s.get(Pedido, 4471).valor_total,
                )
            )
        eng.dispose()
    assert resultados[0] == resultados[1]


# ---------- db.py ----------
def test_recriar_schema_em_sqlite():
    eng = criar_engine("sqlite://")
    recriar_schema(eng)
    with Session(eng) as s:
        s.add(
            Cliente(
                razao_social="X LTDA",
                nome_fantasia="X",
                cnpj="00000000000000",
                telefone_whatsapp="550000",
                contato_nome="Y",
                cidade_uf="BH/MG",
                condicao_pagamento="à vista",
            )
        )
        s.commit()
        assert len(s.scalars(select(Cliente)).all()) == 1
    eng.dispose()
