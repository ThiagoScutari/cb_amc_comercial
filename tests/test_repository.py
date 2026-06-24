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
    StatusTitulo,
    TipoSolicitacao,
    parse_ref_produto,
)
from app.data.repository import MockRepository
from app.data.seed import DEMO_CLIENTE_ID, popular
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
        tipo_cod="036",
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


# --------- parse do ref Colcci (TTT.MM.NNNNN, âncora à direita — v1.8) ---------
def test_parse_ref_ancora_direita_9dig():
    # 340103413 = tipo 034 . marca 01 . ordem 03413 (zeros à esq. do tipo cortados)
    assert parse_ref_produto("340103413") == ("034", "01", "03413")


def test_parse_ref_ancora_direita_8dig():
    # 80104766 = tipo 008 . marca 01 . ordem 04766
    assert parse_ref_produto("80104766") == ("008", "01", "04766")


def test_parse_ref_tipo_3_digitos():
    # 10 díg (teto): tipo de 3 díg sai inteiro, sem perder o zfill nem truncar.
    assert parse_ref_produto("3440103413") == ("344", "01", "03413")


def test_parse_ref_malformado_sem_excecao():
    # < 7 dígitos: derivados null, sem exceção (degrada)
    assert parse_ref_produto("123") == (None, None, None)


def test_parse_ref_acima_do_teto():
    # > 10 díg (teto absoluto = 3+2+5): malformado -> null (não inventa tipo de 4 díg).
    assert parse_ref_produto("12345678901") == (None, None, None)


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
def test_produto_tipo_nullable_para_ref_malformado(session):
    # Com a âncora-direita, derivados só ficam null p/ ref MALFORMADO (<7 díg).
    # O modelo aceita esses nulos (nullable).
    p = _produto(
        sku="123-PP",
        ref_produto="123",
        tipo_cod=None,
        marca_cod=None,
        ordem=None,
        categoria_txt="calcas-e-saias",
        produto="Produto Malformado",
        tamanho="PP",
        cor="Preto",
    )
    session.add(p)
    session.commit()
    got = session.get(Produto, p.id)
    assert got.tipo_cod is None
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


# --------- S13: consultas read-only de NF / título / devolução + faturamento (SQLite) ---------
@pytest.fixture
def repo(session) -> MockRepository:
    popular(session)
    session.flush()
    return MockRepository(session)


def test_consultar_nota_fiscal_propria(repo):
    nf = repo.consultar_nota_fiscal(DEMO_CLIENTE_ID, 60001)
    assert nf is not None
    assert nf.numero_nf == 60001 and nf.cliente_id == DEMO_CLIENTE_ID


def test_consultar_nota_fiscal_inexistente_none(repo):
    assert repo.consultar_nota_fiscal(DEMO_CLIENTE_ID, 99999) is None


def test_consultar_titulo_proprio(repo):
    t = repo.consultar_titulo(DEMO_CLIENTE_ID, "70001")
    assert t is not None and t.numero_titulo == "70001"


def test_consultar_devolucao_propria(repo):
    d = repo.consultar_devolucao(DEMO_CLIENTE_ID, "80001")
    assert d is not None and d.numero_devolucao == "80001"


def test_listar_notas_fiscais_ordenado_e_so_do_cliente(repo):
    nfs = repo.listar_notas_fiscais(DEMO_CLIENTE_ID)
    nums = [n.numero_nf for n in nfs]
    assert nums == [60001, 60002, 60003, 60004, 60005]  # ordem estável por numero_nf
    assert all(n.cliente_id == DEMO_CLIENTE_ID for n in nfs)


def test_listar_titulos_ordenado_e_filtro_status(repo):
    todos = repo.listar_titulos(DEMO_CLIENTE_ID)
    assert len(todos) == 15  # 5 NFs x 3 parcelas (condição "28/35/42 dias")
    vencs = [t.data_vencimento for t in todos]
    assert vencs == sorted(vencs)  # ordenação estável por data_vencimento
    pagos = repo.listar_titulos(DEMO_CLIENTE_ID, filtro_status=StatusTitulo.pago)
    assert len(pagos) == 1 and pagos[0].status == StatusTitulo.pago
    vencidos = repo.listar_titulos(DEMO_CLIENTE_ID, filtro_status=StatusTitulo.vencido)
    assert vencidos and all(t.status == StatusTitulo.vencido for t in vencidos)


def test_listar_devolucoes_ordenado(repo):
    devs = repo.listar_devolucoes(DEMO_CLIENTE_ID)
    assert {d.numero_devolucao for d in devs} == {"80001", "80002", "80003"}
    datas = [d.data_solicitacao for d in devs]
    assert datas == sorted(datas)  # ordem estável por data_solicitacao


def test_consultar_faturamento_demo_bate_o_seed(repo):
    f = repo.consultar_faturamento(DEMO_CLIENTE_ID)
    # contagens fixadas (S12: NFs 60001-60005 -> pedidos 4473..4477)
    assert f["pedidos_total"] == 9
    assert f["pedidos_faturados"] == 5
    assert f["pedidos_a_faturar"] == 4
    # valores: confere com a soma independente dos pedidos COM/SEM NF
    faturados = {4473, 4474, 4475, 4476, 4477}
    peds = repo.session.scalars(select(Pedido).where(Pedido.cliente_id == DEMO_CLIENTE_ID)).all()
    esperado_fat = sum((p.valor_total for p in peds if p.id in faturados), Decimal("0"))
    esperado_af = sum((p.valor_total for p in peds if p.id not in faturados), Decimal("0"))
    assert f["valor_faturado"] == esperado_fat
    assert f["valor_a_faturar"] == esperado_af
    # partição exata: faturado + a_faturar == total do cliente
    assert f["valor_faturado"] + f["valor_a_faturar"] == sum(
        (p.valor_total for p in peds), Decimal("0")
    )
    assert isinstance(f["valor_faturado"], Decimal)


def test_consultar_faturamento_cliente_sem_nf(repo):
    # clientes 3..10 têm pedidos mas NENHUMA NF (S12 só semeia NF p/ clientes 1 e 2)
    f = repo.consultar_faturamento(3)
    assert f["pedidos_total"] >= 1
    assert f["pedidos_faturados"] == 0
    assert f["valor_faturado"] == Decimal("0")
    assert f["pedidos_a_faturar"] == f["pedidos_total"]
