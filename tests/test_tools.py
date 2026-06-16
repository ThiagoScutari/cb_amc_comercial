"""Testes das ferramentas de leitura e do repository (SQLite, sem rede).

Os testes de IDOR de fidelidade (isolamento entre clientes) rodam em Postgres real
em tests/test_idor_postgres.py (contrato A1/A2). Aqui: views, catálogo global,
normalização de telefone e contratos de design.
"""

import pytest
from app.agent.tools import (
    EscalonamentoView,
    EstoqueView,
    Ferramentas,
    NaoEncontrado,
    PedidoView,
    SolicitacaoView,
)
from app.data.models import Cliente, Estoque, Pedido, Solicitacao
from app.data.repository import MockRepository, normalizar_telefone
from app.data.seed import popular
from sqlalchemy import select


@pytest.fixture
def repo(session) -> MockRepository:
    popular(session)
    session.flush()
    return MockRepository(session)


# ---------- leitura própria ----------
def test_consultar_pedido_proprio_com_itens(repo):
    v = Ferramentas(repo, cliente_id=1).consultar_pedido(4471)
    assert isinstance(v, PedidoView)
    assert v.numero == 4471
    assert v.faturado is False
    assert len(v.itens) >= 1


def test_consultar_pedido_de_outro_cliente_nao_encontrado(repo):
    v = Ferramentas(repo, cliente_id=2).consultar_pedido(4471)  # 4471 é do cliente 1
    assert isinstance(v, NaoEncontrado)
    assert v.encontrado is False


def test_listar_pedidos_so_do_proprio_cliente(repo):
    nums_1 = {p.numero for p in Ferramentas(repo, cliente_id=1).listar_pedidos()}
    nums_2 = {p.numero for p in Ferramentas(repo, cliente_id=2).listar_pedidos()}
    assert {4471, 4472, 4473} <= nums_1
    assert nums_1.isdisjoint(nums_2)  # nenhum pedido compartilhado


# ---------- estoque: só saldo (Q2) ----------
def test_estoque_view_expoe_apenas_saldo(repo):
    vs = Ferramentas(repo, cliente_id=1).consultar_disponibilidade(sku="340103413-M")
    assert len(vs) == 1
    dump = vs[0].model_dump()
    assert set(dump) == {"sku", "produto", "cor", "tamanho", "saldo"}
    assert "disponivel" not in dump
    assert "reservado" not in dump
    assert dump["saldo"] == 45  # baseline de demo


def test_estoqueview_nao_tem_campos_internos():
    assert "disponivel" not in EstoqueView.model_fields
    assert "reservado" not in EstoqueView.model_fields


# ---------- itens só via pedido (sem atalho cru) ----------
def test_nao_existe_atalho_de_itens_por_pedido():
    assert not hasattr(MockRepository, "itens_por_pedido")
    assert not hasattr(Ferramentas, "itens_por_pedido")


# ---------- catálogo é GLOBAL (independe do cliente logado) ----------
def test_busca_produto_independe_do_cliente(repo):
    f1 = Ferramentas(repo, cliente_id=1)
    f2 = Ferramentas(repo, cliente_id=2)
    r1 = [v.model_dump() for v in f1.buscar_produto("camiseta")]
    r2 = [v.model_dump() for v in f2.buscar_produto("camiseta")]
    assert r1 == r2
    assert r1  # não vazio


def test_disponibilidade_independe_do_cliente(repo):
    f1 = Ferramentas(repo, cliente_id=1)
    f2 = Ferramentas(repo, cliente_id=2)
    r1 = [v.model_dump() for v in f1.consultar_disponibilidade(produto="camiseta")]
    r2 = [v.model_dump() for v in f2.consultar_disponibilidade(produto="camiseta")]
    assert r1 == r2
    assert r1


# ---------- normalização de telefone (anti-IDOR pela porta dos fundos) ----------
def test_normalizar_telefone_variacoes_mesmo_canonico():
    canonico = "5531999990001"
    for variacao in (
        "5531999990001",
        "+55 31 99999-0001",
        "55 (31) 99999-0001",
        "31999990001",  # sem DDI
        "553199990001",  # sem 9º dígito
        "0055 31 99999 0001",  # prefixo 00
    ):
        assert normalizar_telefone(variacao) == canonico


def test_normalizar_telefone_malformado_vira_none():
    for lixo in ("", None, "abc", "123", "55", "telefone"):
        assert normalizar_telefone(lixo) is None


def test_cliente_por_telefone_resolve_variacoes_para_mesmo_cliente(repo):
    esperado = repo.session.scalars(select(Cliente).where(Cliente.id == 1)).one()
    for variacao in ("5531999990001", "+55 31 99999-0001", "31999990001", "553199990001"):
        c = repo.cliente_por_telefone(variacao)
        assert c is not None
        assert c.id == esperado.id


def test_cliente_por_telefone_desconhecido_ou_lixo(repo):
    assert repo.cliente_por_telefone("5511000000000") is None  # válido mas inexistente
    assert repo.cliente_por_telefone("lixo") is None  # malformado


# ---------- intake (registra + avisa; NUNCA muta) ----------
def test_solicitar_cancelamento_proprio_registra(repo):
    v = Ferramentas(repo, cliente_id=1).solicitar_cancelamento(4471, motivo="desisti")
    assert isinstance(v, SolicitacaoView)
    assert v.tipo == "cancelamento"
    assert v.status == "pendente"
    sols = repo.session.scalars(select(Solicitacao).where(Solicitacao.cliente_id == 1)).all()
    assert any(s.pedido_id == 4471 and s.tipo.value == "cancelamento" for s in sols)


def test_solicitar_cancelamento_de_outro_cliente_nao_encontrado(repo):
    v = Ferramentas(repo, cliente_id=2).solicitar_cancelamento(4471)  # 4471 é do cliente 1
    assert isinstance(v, NaoEncontrado)
    sols = repo.session.scalars(select(Solicitacao).where(Solicitacao.cliente_id == 2)).all()
    assert all(s.pedido_id != 4471 for s in sols)  # nada registrado p/ o cliente 2


def test_solicitar_compra_registra_com_payload(repo):
    v = Ferramentas(repo, cliente_id=1).solicitar_compra(
        [{"sku": "340103413-M", "quantidade": 200}]
    )
    assert v.tipo == "compra"
    assert v.status == "pendente"
    sol = repo.session.get(Solicitacao, v.id)
    assert sol.payload["itens"][0]["sku"] == "340103413-M"
    assert sol.payload["itens"][0]["quantidade"] == 200


def _snap_e_intake(repo, acao):
    antes_status = {p.id: p.status for p in repo.session.scalars(select(Pedido)).all()}
    antes_est = {
        e.sku_id: (e.saldo, e.disponivel, e.reservado)
        for e in repo.session.scalars(select(Estoque)).all()
    }
    n_antes = len(repo.session.scalars(select(Solicitacao)).all())
    acao(Ferramentas(repo, cliente_id=1))
    repo.session.flush()
    depois_status = {p.id: p.status for p in repo.session.scalars(select(Pedido)).all()}
    depois_est = {
        e.sku_id: (e.saldo, e.disponivel, e.reservado)
        for e in repo.session.scalars(select(Estoque)).all()
    }
    assert depois_status == antes_status  # nenhum status de pedido mudou
    assert depois_est == antes_est  # estoque idêntico (saldo/disponivel/reservado)
    assert len(repo.session.scalars(select(Solicitacao)).all()) == n_antes + 1


def test_intake_cancelamento_nao_muta_pedidos_nem_estoque(repo):
    _snap_e_intake(repo, lambda f: f.solicitar_cancelamento(4471, motivo="x"))


def test_intake_compra_nao_muta_estoque_nem_pedidos(repo):
    # caso onde alguém poderia "ajudar" decrementando estoque — NÃO pode.
    _snap_e_intake(repo, lambda f: f.solicitar_compra([{"sku": "340103413-M", "quantidade": 500}]))


def test_ferramenta_escalar_para_humano_registra(repo):
    v = Ferramentas(repo, cliente_id=1).escalar_para_humano("quero falar com uma pessoa")
    assert isinstance(v, EscalonamentoView)
    assert v.registrado is True
