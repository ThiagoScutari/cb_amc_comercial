"""Testes de IDOR de fidelidade em POSTGRES REAL (contrato A1/A2).

Sobe um Postgres efêmero (testcontainers), recria o schema e roda o seed real.
A defesa decisiva é o `WHERE cliente_id` no código (§2.3); aqui provamos o
isolamento entre clientes contra o banco de verdade, não SQLite.

Seed: cliente 1 = demo (dono dos pedidos 4471..4479); cliente 2 = Maré Alta.
"""

import pytest
from app.agent.tools import ClienteView, Ferramentas, NaoEncontrado, PedidoView
from app.data.repository import MockRepository

pytestmark = pytest.mark.postgres

PEDIDOS_DEMO = set(range(4471, 4480))  # do cliente 1

# A fixture `pg_session` (Postgres efêmero + seed real) vive em tests/conftest.py
# — compartilhada com o teste de regressão da sequence (S10).


@pytest.fixture
def repo(pg_session) -> MockRepository:
    return MockRepository(pg_session)


# ---------- adversariais (IDOR) ----------
def test_idor_pedido_de_outro_cliente_retorna_none(repo):
    assert repo.consultar_pedido(cliente_id=2, numero_pedido=4471) is None


def test_idor_itens_inacessiveis_de_outro_cliente(repo):
    # 4471 é do cliente 1; como cliente 2 -> NaoEncontrado, sem caminho para os itens.
    r = Ferramentas(repo, cliente_id=2).consultar_pedido(4471)
    assert isinstance(r, NaoEncontrado)
    assert not hasattr(repo, "itens_por_pedido")  # não há atalho cru


def test_idor_listar_pedidos_nao_vaza_de_outro_cliente(repo):
    nums = {p.id for p in repo.listar_pedidos(cliente_id=2)}
    assert nums.isdisjoint(PEDIDOS_DEMO)


def test_idor_solicitacao_de_outro_cliente_nao_aparece(repo):
    assert repo.listar_solicitacoes(cliente_id=2) == []  # a pendente é do cliente 1
    assert len(repo.listar_solicitacoes(cliente_id=1)) >= 1


def test_idor_ferramenta_responde_nao_encontrado(repo):
    assert isinstance(Ferramentas(repo, cliente_id=2).consultar_pedido(4471), NaoEncontrado)


# ---------- adversariais de borda (cliente_id) ----------
def test_idor_cliente_id_inexistente_retorna_none(repo):
    # cliente_id que não existe -> None limpo, sem exceção, sem vazar.
    assert repo.consultar_pedido(cliente_id=99999, numero_pedido=4471) is None


def test_pedido_inexistente_retorna_none(repo):
    # idêntico ao IDOR: inexistente também é None (não dá p/ distinguir).
    assert repo.consultar_pedido(cliente_id=1, numero_pedido=999999) is None


# ---------- dados do cliente (S09a) — cada sessão só vê a própria conta ----------
def test_idor_dados_cliente_so_da_propria_sessao(repo):
    # cliente 2 (Maré Alta) NUNCA enxerga a condição do cliente 1 (Boutique Aurora).
    v = Ferramentas(repo, cliente_id=2).consultar_dados_cliente()
    assert isinstance(v, ClienteView)
    assert v.condicao_pagamento == "à vista" and v.cidade_uf == "Vitória/ES"  # do cliente 2
    assert v.condicao_pagamento != "28/35/42 dias"  # nunca a do cliente 1


def test_dados_cliente_proprio_em_postgres(repo):
    v = Ferramentas(repo, cliente_id=1).consultar_dados_cliente()
    assert v.condicao_pagamento == "28/35/42 dias" and v.cidade_uf == "Belo Horizonte/MG"


# ---------- controles positivos ----------
def test_cliente_acessa_proprio_pedido_com_itens(repo):
    v = Ferramentas(repo, cliente_id=1).consultar_pedido(4471)
    assert isinstance(v, PedidoView)
    assert v.numero == 4471
    assert len(v.itens) >= 1


def test_catalogo_global_em_postgres(repo):
    assert repo.buscar_produto("camiseta")  # catálogo acessível, sem cliente_id


# ---------- IDOR no caminho de ESCRITA (intake) ----------
def test_idor_cancelamento_de_outro_cliente_nao_registra(repo):
    # cliente 2 tenta cancelar 4471 (do cliente 1): negado e NADA registrado.
    n_antes = len(repo.listar_solicitacoes(2))
    sol = repo.registrar_cancelamento(cliente_id=2, numero_pedido=4471)
    assert sol is None
    assert len(repo.listar_solicitacoes(2)) == n_antes
    repo.session.rollback()


def test_cancelamento_proprio_registra(repo):
    # controle positivo: o dono (cliente 1) consegue registrar.
    sol = repo.registrar_cancelamento(cliente_id=1, numero_pedido=4471, motivo="teste")
    assert sol is not None
    assert sol.cliente_id == 1
    assert sol.tipo.value == "cancelamento"
    repo.session.rollback()


# ---------- S13: IDOR cross-client das entidades fiscais (read-only) ----------
# Seed S12: cliente 1 dono de NF 60001-60005, títulos 70001-70015, devoluções 80001-80003;
# cliente 2 dono de NF 60006, título 70016, devolução 80004.
def test_idor_nota_fiscal_de_outro_cliente_none(repo):
    assert repo.consultar_nota_fiscal(cliente_id=2, numero_nf=60001) is None  # 60001 é do cliente 1


def test_idor_titulo_de_outro_cliente_none(repo):
    assert repo.consultar_titulo(cliente_id=2, numero_titulo="70001") is None


def test_idor_devolucao_de_outro_cliente_none(repo):
    assert repo.consultar_devolucao(cliente_id=2, numero_devolucao="80001") is None


def test_idor_cliente1_nao_ve_nf_do_cliente2(repo):
    assert repo.consultar_nota_fiscal(cliente_id=1, numero_nf=60006) is None  # 60006 é do cliente 2


def test_idor_listagens_fiscais_nao_vazam_entre_clientes(repo):
    nfs2 = {n.numero_nf for n in repo.listar_notas_fiscais(2)}
    assert 60006 in nfs2
    assert nfs2.isdisjoint({60001, 60002, 60003, 60004, 60005})
    tit2 = {t.numero_titulo for t in repo.listar_titulos(2)}
    assert "70016" in tit2
    assert tit2.isdisjoint({str(n) for n in range(70001, 70016)})  # nenhum título do cliente 1
    dev2 = {d.numero_devolucao for d in repo.listar_devolucoes(2)}
    assert dev2 == {"80004"}
    # e o cliente 1 NÃO vê nada do cliente 2
    assert 60006 not in {n.numero_nf for n in repo.listar_notas_fiscais(1)}
    assert "70016" not in {t.numero_titulo for t in repo.listar_titulos(1)}


def test_idor_faturamento_escopado_ao_cliente(repo):
    f2 = repo.consultar_faturamento(cliente_id=2)
    # cliente 2: 2 pedidos (4450, 4451); só 4450 tem NF (60006). Nada do cliente 1 entra.
    assert f2["pedidos_total"] == 2
    assert f2["pedidos_faturados"] == 1
    assert f2["pedidos_a_faturar"] == 1
    ped4450 = repo.consultar_pedido(2, 4450)
    assert f2["valor_faturado"] == ped4450.valor_total  # só o pedido faturado do cliente 2
