"""Testes do gerador de resumo visual de pedidos em HTML (app/report/resumo_pedidos.py).

Determinísticos, sem rede, sem disco. Cobrem: conteúdo (número/status/RefId/valor/
data), lista vazia, autoescape (segurança) e ANTI-IDOR (o HTML de um cliente só mostra
os pedidos dele — os pedidos vêm de listar_pedidos, que já filtra por cliente_id).
"""

import pytest
from app.data.repository import MockRepository
from app.data.seed import popular
from app.report.resumo_pedidos import gerar_html_pedidos


@pytest.fixture
def repo(session) -> MockRepository:
    popular(session)
    session.flush()
    return MockRepository(session)


def test_html_contem_dados_dos_pedidos(repo):
    html = gerar_html_pedidos("Boutique Aurora", repo.listar_pedidos(1))
    assert "<!DOCTYPE html>" in html and "</html>" in html
    assert "Boutique Aurora" in html
    assert "4471" in html  # número do pedido
    assert "Confirmado" in html  # status (pedido 4471)
    assert "340103413" in html  # RefId da peça (camiseta branca M do 4471)
    assert "R$" in html  # valor formatado
    assert "/2026" in html  # data dd/mm/aaaa


def test_lista_vazia_gera_html_valido(repo):
    html = gerar_html_pedidos("Loja Sem Pedidos", [])
    assert "<!DOCTYPE html>" in html and "</html>" in html
    assert "nenhum pedido" in html.lower()


def test_autoescape_neutraliza_html_no_nome(repo):
    html = gerar_html_pedidos("<script>alert('x')</script>", repo.listar_pedidos(1))
    assert "<script>alert" not in html  # não injeta tag executável
    assert "&lt;script&gt;" in html  # foi escapado


def test_anti_idor_cliente_so_ve_os_proprios_pedidos(repo):
    nums_1 = {p.id for p in repo.listar_pedidos(1)}
    nums_2 = {p.id for p in repo.listar_pedidos(2)}
    assert nums_1 and nums_2 and nums_1.isdisjoint(nums_2)  # sanidade do seed

    html_1 = gerar_html_pedidos("Cliente 1", repo.listar_pedidos(1))
    # Nenhum número de pedido do cliente 2 pode aparecer no HTML do cliente 1.
    for n in nums_2:
        assert str(n) not in html_1
    assert str(next(iter(nums_1))) in html_1  # mas os dele aparecem


def test_sem_efeito_de_rede_ou_cdn_no_html(repo):
    # Renderiza offline: nada de <script src> externo (Chart.js/CDN removido de propósito).
    html = gerar_html_pedidos("Boutique Aurora", repo.listar_pedidos(1))
    assert "cdn.jsdelivr" not in html
    assert "<script src" not in html
