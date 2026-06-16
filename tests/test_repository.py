"""Testes dos modelos SQLAlchemy e do parse do código Colcci (Fase 1, §5)."""

import datetime as dt
from decimal import Decimal

import pytest
from app.data.models import (
    Cliente,
    Estoque,
    Pedido,
    PedidoItem,
    Produto,
    Solicitacao,
    StatusPedido,
    StatusSolicitacao,
    TipoSolicitacao,
    parse_ref_produto,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError


# --------- helpers de construção (defaults sensatos) ---------
def _cliente(**kw) -> Cliente:
    base = dict(
        razao_social="Loja Exemplo LTDA",
        nome_fantasia="Loja Exemplo",
        cnpj="12345678000190",
        telefone_whatsapp="5531999990001",
        contato_nome="Fulano de Tal",
        cidade_uf="Belo Horizonte/MG",
        condicao_pagamento="28/35/42 dias",
    )
    base.update(kw)
    return Cliente(**base)


def _produto(**kw) -> Produto:
    base = dict(
        sku="360118439-M",
        ref_produto="360118439",
        categoria_cod="36",
        marca_cod="01",
        ordem="18439",
        genero="Feminino",
        categoria_txt="camisetas-e-regatas",
        produto="Blusa Estruturada Bustier",
        tamanho="M",
        cor="Verde Vanity",
        preco_tabela=Decimal("199.90"),
    )
    base.update(kw)
    return Produto(**base)


def _pedido(**kw) -> Pedido:
    base = dict(
        id=4471,
        data_pedido=dt.date(2026, 6, 1),
        status=StatusPedido.confirmado,
        data_prevista_entrega=dt.date(2026, 6, 20),
        valor_total=Decimal("0.00"),
    )
    base.update(kw)
    return Pedido(**base)


# --------- parse do ref Colcci ---------
def test_parse_ref_produto_valido():
    assert parse_ref_produto("360118439") == ("36", "01", "18439")


def test_parse_ref_produto_tamanho_invalido():
    with pytest.raises(ValueError):
        parse_ref_produto("12345")


def test_parse_ref_produto_nao_numerico():
    with pytest.raises(ValueError):
        parse_ref_produto("36011843X")


# --------- clientes ---------
def test_cliente_roundtrip_e_ativo_default(session):
    session.add(_cliente())
    session.commit()
    c = session.scalars(select(Cliente)).one()
    assert c.id is not None
    assert c.ativo is True
    assert c.telefone_whatsapp == "5531999990001"


def test_telefone_whatsapp_e_unico(session):
    session.add(_cliente())
    session.commit()
    session.add(_cliente(cnpj="99999999000199"))  # mesmo telefone, CNPJ diferente
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


# --------- pedido + itens + relacionamentos ---------
def test_pedido_relacionamentos_e_id_inserivel(session):
    cliente = _cliente()
    produto = _produto()
    session.add_all([cliente, produto])
    session.flush()

    pedido = _pedido(cliente_id=cliente.id, valor_total=Decimal("399.80"))
    pedido.itens.append(
        PedidoItem(sku_id=produto.id, quantidade=2, preco_unitario=Decimal("199.90"))
    )
    session.add(pedido)
    session.commit()

    p = session.get(Pedido, 4471)  # id realista inserido explicitamente
    assert p.cliente.id == cliente.id
    assert len(p.itens) == 1
    assert p.itens[0].sku.sku == "360118439-M"


# --------- faturado derivado do status (ajuste do arquiteto) ---------
@pytest.mark.parametrize(
    "status,esperado",
    [
        (StatusPedido.em_analise, False),
        (StatusPedido.confirmado, False),
        (StatusPedido.faturado, True),
        (StatusPedido.em_separacao, True),
        (StatusPedido.despachado, True),
        (StatusPedido.em_transito, True),
        (StatusPedido.entregue, True),
        (StatusPedido.cancelamento_solicitado, False),
        (StatusPedido.cancelado, False),
    ],
)
def test_faturado_derivado_do_status(status, esperado):
    assert _pedido(status=status).faturado is esperado


def test_query_filtra_pedidos_faturados(session):
    cliente = _cliente()
    session.add(cliente)
    session.flush()
    session.add_all(
        [
            _pedido(id=1001, cliente_id=cliente.id, status=StatusPedido.faturado),
            _pedido(id=1002, cliente_id=cliente.id, status=StatusPedido.confirmado),
        ]
    )
    session.commit()

    faturados = session.scalars(select(Pedido).where(Pedido.faturado)).all()
    assert [p.id for p in faturados] == [1001]


# --------- estoque (saldo/disponivel/reservado) ---------
def test_produto_ref8_derivados_nullable(session):
    # ref de 8 dígitos: categoria_cod/marca_cod/ordem ficam null (nunca inventar).
    p = _produto(
        sku="80104766-PP",
        ref_produto="80104766",
        categoria_cod=None,
        marca_cod=None,
        ordem=None,
        categoria_txt="calcas-e-saias",
        produto="Saia Curta Essential Poliamida",
        tamanho="PP",
        cor="Preto",
    )
    session.add(p)
    session.commit()
    got = session.get(Produto, p.id)
    assert got.categoria_cod is None
    assert got.marca_cod is None
    assert got.ordem is None
    assert got.genero == "Feminino"
    assert got.categoria_txt == "calcas-e-saias"


def test_produto_genero_obrigatorio(session):
    session.add(_produto(genero=None))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_estoque_1a1_e_campos(session):
    produto = _produto()
    session.add(produto)
    session.flush()
    session.add(Estoque(sku_id=produto.id, saldo=10, disponivel=3, reservado=2))
    session.commit()

    prod = session.get(Produto, produto.id)
    assert prod.estoque.saldo == 10
    assert prod.estoque.disponivel == 3
    assert prod.estoque.reservado == 2


def test_estoque_nao_aceita_negativo(session):
    produto = _produto()
    session.add(produto)
    session.flush()
    session.add(Estoque(sku_id=produto.id, saldo=-1))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


# --------- solicitacoes (intake) ---------
def test_solicitacao_status_pendente_default(session):
    cliente = _cliente()
    session.add(cliente)
    session.flush()
    s = Solicitacao(
        cliente_id=cliente.id,
        tipo=TipoSolicitacao.cancelamento,
        pedido_id=None,
        payload={"motivo": "desistência"},
    )
    session.add(s)
    session.commit()
    session.refresh(s)  # carrega criado_em (server_default)

    assert s.status is StatusSolicitacao.pendente
    assert s.criado_em is not None
    assert s.payload["motivo"] == "desistência"
