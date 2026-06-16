"""Testes de IDOR de fidelidade em POSTGRES REAL (contrato A1/A2).

Sobe um Postgres efêmero (testcontainers), recria o schema e roda o seed real.
A defesa decisiva é o `WHERE cliente_id` no código (§2.3); aqui provamos o
isolamento entre clientes contra o banco de verdade, não SQLite.

Seed: cliente 1 = demo (dono dos pedidos 4471..4479); cliente 2 = Maré Alta.
"""

import pytest
from app.agent.tools import Ferramentas, NaoEncontrado, PedidoView
from app.data.db import recriar_schema
from app.data.repository import MockRepository
from app.data.seed import popular
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

pytestmark = pytest.mark.postgres

PEDIDOS_DEMO = set(range(4471, 4480))  # do cliente 1


@pytest.fixture(scope="module")
def pg_session():
    try:
        from testcontainers.postgres import PostgresContainer
    except ImportError:  # pragma: no cover
        pytest.skip("testcontainers não instalado")
    try:
        container = PostgresContainer("postgres:15", driver="psycopg")
        container.start()
    except Exception as exc:  # pragma: no cover - Docker ausente
        pytest.skip(f"Docker indisponível: {exc}")
    try:
        engine = create_engine(container.get_connection_url())
        recriar_schema(engine)
        with Session(engine) as s:
            popular(s)
            s.commit()
        with Session(engine) as s:
            yield s
        engine.dispose()
    finally:
        container.stop()


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


# ---------- controles positivos ----------
def test_cliente_acessa_proprio_pedido_com_itens(repo):
    v = Ferramentas(repo, cliente_id=1).consultar_pedido(4471)
    assert isinstance(v, PedidoView)
    assert v.numero == 4471
    assert len(v.itens) >= 1


def test_catalogo_global_em_postgres(repo):
    assert repo.buscar_produto("camiseta")  # catálogo acessível, sem cliente_id
