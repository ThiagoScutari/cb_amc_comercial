"""Testes do cadastro de cliente-demo sob demanda (scripts.cadastrar_demo).

SQLite in-memory com o seed real pré-carregado. Validam: invariantes coerentes,
faixa única (sem colidir com 4471–4479), telefone normalizado casando com
resolver_sessao, idempotência (re-run não duplica) e anti-IDOR do cadastrado.
"""

from decimal import Decimal

import pytest
from app.agent.tools import Ferramentas, NaoEncontrado, PedidoView
from app.auth.session import SessaoAutenticada, resolver_sessao
from app.data.models import Devolucao, NotaFiscal, Pedido, StatusPedido, Titulo
from app.data.repository import MockRepository
from app.data.seed import popular
from scripts.cadastrar_demo import FAIXA_BASE, ResumoCadastro, cadastrar
from sqlalchemy import select


@pytest.fixture
def repo(session) -> MockRepository:
    popular(session)  # seed real: clientes 1..3, pedidos 4471..4479 e 4450..4453
    session.flush()
    return MockRepository(session)


def _pedidos(session, cliente_id) -> list[Pedido]:
    return list(session.scalars(select(Pedido).where(Pedido.cliente_id == cliente_id)).all())


# ---------- criação + invariantes ----------
def test_cadastra_cinco_pedidos_com_invariantes(repo):
    r = cadastrar(repo.session, "5547999998888", "Boutique do João")
    assert isinstance(r, ResumoCadastro) and r.acao == "criado"

    pedidos = _pedidos(repo.session, _cliente_id_por_tel(repo, "5547999998888"))
    assert len(pedidos) == 5
    # valor_total = Σ(quantidade × preço) — invariante do criar_pedido
    for p in pedidos:
        esperado = sum((Decimal(it.quantidade) * it.preco_unitario for it in p.itens), Decimal("0"))
        assert p.valor_total == esperado
        assert p.itens, "pedido sem itens"
    # status cobrem o conjunto pedido (decisão A)
    status = {p.status for p in pedidos}
    assert status == {
        StatusPedido.em_analise,
        StatusPedido.confirmado,
        StatusPedido.em_transito,
        StatusPedido.entregue,
        StatusPedido.faturado,
    }


def test_resumo_explicita_cancelavel_e_consultavel(repo):
    r = cadastrar(repo.session, "5547999998888", "Boutique do João")
    # o cancelável é o não-faturado (em_análise); o consultável tem a camiseta branca M
    canc = repo.session.get(Pedido, r.cancelavel)
    cons = repo.session.get(Pedido, r.consultavel)
    assert canc.status == StatusPedido.em_analise
    assert cons.status == StatusPedido.confirmado
    texto = str(r)
    assert f"CANCELÁVEL: {r.cancelavel}" in texto and f"CONSULTÁVEL no {r.consultavel}" in texto


# ---------- faixa única ----------
def test_faixa_acima_do_seed_e_sem_colisao(repo):
    r = cadastrar(repo.session, "5547999998888", "Boutique do João")
    assert r.faixa_ini >= FAIXA_BASE
    assert set(range(r.faixa_ini, r.faixa_fim + 1)).isdisjoint(set(range(4450, 4480)))


def test_dois_clientes_recebem_faixas_disjuntas(repo):
    r1 = cadastrar(repo.session, "5547999998888", "Loja Um")
    r2 = cadastrar(repo.session, "5531977776666", "Loja Dois")
    faixa1 = set(range(r1.faixa_ini, r1.faixa_fim + 1))
    faixa2 = set(range(r2.faixa_ini, r2.faixa_fim + 1))
    assert faixa1.isdisjoint(faixa2)


# ---------- telefone normalizado casa com a auth ----------
def test_telefone_normalizado_autentica_no_resolver_sessao(repo):
    cadastrar(repo.session, "+55 (47) 99999-8888", "Boutique do João")
    # o mesmo número em formato "sujo" deve autenticar (resolver_sessao normaliza igual)
    sessao = resolver_sessao("55 47 99999 8888", repo)
    assert isinstance(sessao, SessaoAutenticada)
    assert sessao.nome == "Boutique do João"


# ---------- idempotência ----------
def test_rerun_mesmo_telefone_nao_duplica(repo):
    r1 = cadastrar(repo.session, "5547999998888", "Boutique do João")
    cid = _cliente_id_por_tel(repo, "5547999998888")
    r2 = cadastrar(repo.session, "5547999998888", "Boutique do João (novo nome)")
    # 1 cliente, 5 pedidos, MESMA faixa
    assert _cliente_id_por_tel(repo, "5547999998888") == cid
    assert len(_pedidos(repo.session, cid)) == 5
    assert (r2.faixa_ini, r2.faixa_fim) == (r1.faixa_ini, r1.faixa_fim)
    assert r2.acao == "atualizado"


# ---------- anti-IDOR ----------
def test_idor_cadastrado_nao_ve_pedido_de_outro(repo):
    r1 = cadastrar(repo.session, "5547999998888", "Loja Um")
    cadastrar(repo.session, "5531977776666", "Loja Dois")
    cid1 = _cliente_id_por_tel(repo, "5547999998888")
    # Loja Um acessa o próprio consultável...
    proprio = Ferramentas(repo, cid1).consultar_pedido(r1.consultavel)
    assert isinstance(proprio, PedidoView)
    # ...mas NÃO o cancelável do seed (4471) nem o do outro cadastrado
    assert isinstance(Ferramentas(repo, cid1).consultar_pedido(4471), NaoEncontrado)
    r2_consultavel = _pedidos(repo.session, _cliente_id_por_tel(repo, "5531977776666"))[0].id
    assert isinstance(Ferramentas(repo, cid1).consultar_pedido(r2_consultavel), NaoEncontrado)


def _cliente_id_por_tel(repo, telefone) -> int:
    c = repo.cliente_por_telefone(telefone)
    assert c is not None
    return c.id


# ---------- S17b: fiscal (NF/título/devolução) do cliente cadastrado ----------
def _fiscal(repo, cid):
    nfs = repo.session.scalars(select(NotaFiscal).where(NotaFiscal.cliente_id == cid)).all()
    tits = repo.session.scalars(select(Titulo).where(Titulo.cliente_id == cid)).all()
    devs = repo.session.scalars(select(Devolucao).where(Devolucao.cliente_id == cid)).all()
    return list(nfs), list(tits), list(devs)


def test_cadastro_cria_fiscal_na_faixa_90xxx(repo):
    cadastrar(repo.session, "5547999998888", "Boutique do João")
    cid = _cliente_id_por_tel(repo, "5547999998888")
    nfs, tits, devs = _fiscal(repo, cid)
    assert (
        len(nfs) == 3 and tits and devs
    )  # 3 pedidos faturados -> 3 NFs; títulos e ao menos 1 devol.
    assert all(90000 <= nf.numero_nf < 93000 for nf in nfs)
    assert all(t.numero_titulo.startswith("91") for t in tits)
    assert all(d.numero_devolucao.startswith("92") for d in devs)


def test_fiscal_cadastrado_invariantes(repo):
    cadastrar(repo.session, "5547999998888", "Boutique do João")
    cid = _cliente_id_por_tel(repo, "5547999998888")
    nfs, _, devs = _fiscal(repo, cid)
    for nf in nfs:
        assert nf.valor_total == repo.session.get(Pedido, nf.pedido_id).valor_total  # NF = pedido
        soma = sum(
            (
                t.valor
                for t in repo.session.scalars(
                    select(Titulo).where(Titulo.nota_fiscal_id == nf.id)
                ).all()
            ),
            Decimal("0"),
        )
        assert soma == nf.valor_total  # Σ parcelas == NF
    for d in devs:  # crédito = valor da NF
        assert d.valor_credito == repo.session.get(NotaFiscal, d.nota_fiscal_id).valor_total


def test_fiscal_numeracao_disjunta_entre_clientes_e_do_seed(repo):
    cadastrar(repo.session, "5547999998888", "Loja Um")
    cadastrar(repo.session, "5531977776666", "Loja Dois")
    cid1 = _cliente_id_por_tel(repo, "5547999998888")
    cid2 = _cliente_id_por_tel(repo, "5531977776666")
    nf1 = {nf.numero_nf for nf in _fiscal(repo, cid1)[0]}
    nf2 = {nf.numero_nf for nf in _fiscal(repo, cid2)[0]}
    assert nf1 and nf2 and nf1.isdisjoint(nf2)  # entre cadastrados
    seed_nfs = {
        nf.numero_nf
        for nf in repo.session.scalars(
            select(NotaFiscal).where(NotaFiscal.cliente_id.in_([1, 2]))
        ).all()
    }
    assert nf1.isdisjoint(seed_nfs) and nf2.isdisjoint(seed_nfs)  # disjunto do seed (60xxx)


def test_fiscal_idempotente_rerun_nao_duplica(repo):
    cadastrar(repo.session, "5547999998888", "Boutique do João")
    cid = _cliente_id_por_tel(repo, "5547999998888")
    cadastrar(repo.session, "5547999998888", "Boutique do João (re)")  # re-run mesmo telefone
    nfs, _, devs = _fiscal(repo, cid)
    assert len(nfs) == 3 and len(devs) == 1  # não duplicou


def test_fiscal_cadastrado_anti_idor(repo):
    cadastrar(repo.session, "5547999998888", "Loja Um")
    cid1 = _cliente_id_por_tel(repo, "5547999998888")
    nf1 = _fiscal(repo, cid1)[0][0].numero_nf
    assert repo.consultar_nota_fiscal(1, nf1) is None  # cliente do seed não vê a NF do cadastrado
    assert repo.consultar_nota_fiscal(cid1, 60001) is None  # cadastrado não vê a NF do seed
    assert repo.consultar_nota_fiscal(cid1, nf1) is not None  # mas vê a própria
