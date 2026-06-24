"""Testes do gerador de resumo visual de pedidos em HTML (app/report/resumo_pedidos.py).

Determinísticos, sem rede, sem disco. Cobrem: conteúdo (número/status/RefId/valor/
data), lista vazia, autoescape (segurança) e ANTI-IDOR (o HTML de um cliente só mostra
os pedidos dele — os pedidos vêm de listar_pedidos, que já filtra por cliente_id).
"""

import pytest
from app.data.repository import MockRepository
from app.data.seed import popular
from app.report.resumo_pedidos import (
    gerar_html_devolucoes,
    gerar_html_notas,
    gerar_html_pedidos,
    gerar_html_titulos,
)


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


# ---------- S16: renderers de NF / título / devolução ----------
def test_html_notas_contem_dados(repo):
    html = gerar_html_notas("Boutique Aurora", repo.listar_notas_fiscais(1))
    assert "<!DOCTYPE html>" in html and "</html>" in html
    assert "Notas Fiscais" in html and "Boutique Aurora" in html
    assert "60001" in html  # número da NF do cliente-demo
    assert "R$" in html and "/2026" in html


def test_html_titulos_mostra_vencidos(repo):
    html = gerar_html_titulos("Loja", repo.listar_titulos(1))
    assert "70013" in html  # título vencido do seed
    assert "Vencido" in html


def test_html_devolucoes_contem_status_e_credito(repo):
    html = gerar_html_devolucoes("Loja", repo.listar_devolucoes(1))
    assert "80003" in html  # devolução com crédito gerado
    assert "Crédito gerado" in html


def test_listas_vazias_geram_html_valido():
    for gen, marca in [
        (gerar_html_notas, "nota fiscal"),
        (gerar_html_titulos, "título"),
        (gerar_html_devolucoes, "devolução"),
    ]:
        html = gen("Loja Vazia", [])
        assert "<!DOCTYPE html>" in html and "</html>" in html
        assert marca in html.lower()  # estado vazio menciona a entidade


def test_autoescape_neutraliza_xss_no_motivo_de_devolucao(repo):
    # campo de texto livre (motivo) com <script> é ESCAPADO, não executado.
    devs = repo.listar_devolucoes(1)
    devs[0].motivo = "<script>alert('x')</script>"
    html = gerar_html_devolucoes("Loja", devs)
    assert "<script>alert" not in html
    assert "&lt;script&gt;" in html


def test_novos_renderers_sem_cdn_nem_script(repo):
    for html in (
        gerar_html_notas("Loja", repo.listar_notas_fiscais(1)),
        gerar_html_titulos("Loja", repo.listar_titulos(1)),
        gerar_html_devolucoes("Loja", repo.listar_devolucoes(1)),
    ):
        assert "cdn.jsdelivr" not in html and "<script src" not in html


def test_renderer_so_pinta_a_lista_recebida(repo):
    # Isolamento: o renderer só mostra o que recebe (lista do dono, já filtrada por cliente_id).
    nfs_2 = repo.listar_notas_fiscais(2)  # NFs do cliente 2
    html_1 = gerar_html_notas("Cliente 1", repo.listar_notas_fiscais(1))
    assert nfs_2  # sanidade: cliente 2 tem NF no seed
    for nf in nfs_2:
        assert str(nf.numero_nf) not in html_1  # nenhuma NF do cliente 2 no HTML do cliente 1


# ---------- S18c: HTML -> PDF (a Cloud API rejeita text/html como documento) ----------
# WeasyPrint exige libs nativas (Pango/Cairo) — ausentes no dev Windows. Estes testes pulam
# onde o WeasyPrint não importa e RODAM no container/CI (onde o Dockerfile instala as libs).
def test_html_para_pdf_gera_pdf_valido(repo):
    pytest.importorskip("weasyprint")
    from app.report.pdf import html_para_pdf

    for html in (
        gerar_html_pedidos("Boutique Aurora", repo.listar_pedidos(1)),
        gerar_html_notas("Boutique Aurora", repo.listar_notas_fiscais(1)),
        gerar_html_titulos("Boutique Aurora", repo.listar_titulos(1)),
        gerar_html_devolucoes("Boutique Aurora", repo.listar_devolucoes(1)),
    ):
        pdf = html_para_pdf(html)
        assert pdf[:5] == b"%PDF-"  # magic de PDF
        assert len(pdf) > 500  # não-vazio / página renderizada de verdade


def test_html_para_pdf_de_lista_vazia_tambem_renderiza():
    pytest.importorskip("weasyprint")
    from app.report.pdf import html_para_pdf

    pdf = html_para_pdf(gerar_html_notas("Loja Vazia", []))
    assert pdf[:5] == b"%PDF-"


def test_pdf_nao_reintroduz_xss(repo):
    # Anti-XSS herdado: o HTML já vem ESCAPADO (autoescape, testado acima). O WeasyPrint
    # renderiza um documento — não executa <script>. O PDF é derivado do HTML escapado, sem
    # reintroduzir a tag executável.
    pytest.importorskip("weasyprint")
    from app.report.pdf import html_para_pdf

    devs = repo.listar_devolucoes(1)
    devs[0].motivo = "<script>alert('x')</script>"
    html = gerar_html_devolucoes("Loja", devs)
    assert "<script>alert" not in html and "&lt;script&gt;" in html  # já escapado no HTML
    assert html_para_pdf(html)[:5] == b"%PDF-"  # renderiza sem reintroduzir a tag
