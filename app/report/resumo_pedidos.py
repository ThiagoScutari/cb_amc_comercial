"""Cópia visual em HTML das listas do cliente (pedidos, NF, título, devolução). SEM REDE/DISCO.

Funções puras: recebem listas JÁ FILTRADAS por cliente_id (os `listar_*` do repository
filtram — anti-IDOR) e devolvem uma página HTML autocontida. O HTML NÃO consulta o banco;
recebe a lista pronta — sem nova superfície de IDOR.

Base única (`_SHELL`): cabeçalho + CSS (tema escuro, cards, tabela, mobile-first) + rodapé,
com `autoescape` ON — nome/produto/motivo/transportadora nunca injetam HTML. Sem `<script>`/
CDN: abre offline. Pedidos mantém seu corpo bespoke (peças multi-linha) e sai byte-idêntico
ao original; NF/título/devolução usam um corpo genérico (tabela de colunas configuráveis).

É ADITIVO no fluxo (router.py): se gerar/enviar falhar, o bot já respondeu em texto.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from jinja2 import Template

from app.data.models import Devolucao, NotaFiscal, Pedido, StatusTitulo, Titulo

# Shell base (cabeçalho/CSS/rodapé), parametrizada pelo título e com o corpo já-renderizado
# (e JÁ escapado) injetado como seguro. CSS reaproveitado do dashboard_service.py do
# chatbot_sheet_talk. Sem <script>/CDN: a página abre offline no navegador do celular.
_SHELL = Template(
    """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{{ titulo }} — {{ nome_cliente }}</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: #060A13; color: #EAF0FA; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; padding: 12px; max-width: 100vw; overflow-x: hidden; }
  h1 { font-size: 1.1rem; color: #EAF0FA; margin-bottom: 4px; text-align: center; }
  .sub { font-size: 0.75rem; color: #7B8BA6; text-align: center; margin-bottom: 16px; }
  .cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(110px, 1fr)); gap: 12px; margin-bottom: 20px; }
  .card { background: #0C1220; border: 1px solid #1C2740; border-radius: 10px; padding: 14px 10px; text-align: center; overflow: hidden; word-break: break-word; }
  .card .value { font-size: 1.5rem; font-weight: 700; color: #EAF0FA; }
  .card .label { font-size: 0.7rem; color: #7B8BA6; margin-top: 4px; text-transform: uppercase; letter-spacing: 0.05em; }
  .panel { background: #0C1220; border: 1px solid #1C2740; border-radius: 10px; padding: 16px; }
  table { width: 100%; border-collapse: collapse; font-size: 12px; }
  th { padding: 8px 10px; text-align: left; color: #3B82F6; border-bottom: 2px solid #1C2740; white-space: nowrap; }
  td { padding: 8px 10px; color: #EAF0FA; border-bottom: 1px solid #1C2740; vertical-align: top; }
  td.peca { color: #7B8BA6; }
  .ref { color: #7B8BA6; font-size: 11px; }
  .status { font-weight: 700; }
  .vazio { color: #7B8BA6; text-align: center; padding: 24px; }
</style>
</head>
<body>
<h1>{{ titulo }}</h1>
<div class="sub">{{ nome_cliente }}</div>
{{ corpo|safe }}
</body>
</html>""",
    autoescape=True,
)

# Corpo bespoke de PEDIDOS (cards + tabela com a célula multi-linha de peças). Extraído
# verbatim do template original para que a saída de gerar_html_pedidos seja byte-idêntica.
# Começa com '\n' (a linha em branco antes dos cards) e termina no </div> do painel.
_CORPO_PEDIDOS = Template(
    """
<div class="cards">
  <div class="card"><div class="value">{{ total_pedidos }}</div><div class="label">Pedidos</div></div>
  <div class="card"><div class="value">{{ total_pecas }}</div><div class="label">Peças</div></div>
  <div class="card"><div class="value">{{ valor_total }}</div><div class="label">Valor total</div></div>
</div>

<div class="panel">
{% if linhas %}
  <table>
    <thead>
      <tr><th>Pedido</th><th>Status</th><th>Peças</th><th>Valor</th><th>Data</th></tr>
    </thead>
    <tbody>
      {% for l in linhas %}
      <tr>
        <td><strong>{{ l.numero }}</strong></td>
        <td class="status">{{ l.status }}</td>
        <td class="peca">
          {% for p in l.pecas %}{{ p.qtd }}x {{ p.nome }} <span class="ref">(ref {{ p.ref }})</span><br>{% endfor %}
        </td>
        <td>{{ l.valor }}</td>
        <td>{{ l.data }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
{% else %}
  <div class="vazio">Você ainda não tem nenhum pedido por aqui.</div>
{% endif %}
</div>""",
    autoescape=True,
)

# Corpo GENÉRICO (cards opcionais + tabela de colunas configuráveis), usado por NF/título/
# devolução. Cada linha é uma lista de células {valor, classe?}; `autoescape` ON escapa todo
# valor. Não precisa ser byte-igual a nada — é estrutura nova.
_CORPO_GENERICO = Template(
    """
{% if cards %}<div class="cards">
  {% for c in cards %}<div class="card"><div class="value">{{ c.value }}</div><div class="label">{{ c.label }}</div></div>
  {% endfor %}</div>

{% endif %}<div class="panel">
{% if linhas %}
  <table>
    <thead>
      <tr>{% for col in colunas %}<th>{{ col }}</th>{% endfor %}</tr>
    </thead>
    <tbody>
      {% for linha in linhas %}
      <tr>{% for cel in linha %}<td{% if cel.classe %} class="{{ cel.classe }}"{% endif %}>{{ cel.valor }}</td>{% endfor %}</tr>
      {% endfor %}
    </tbody>
  </table>
{% else %}
  <div class="vazio">{{ vazio_msg }}</div>
{% endif %}
</div>""",
    autoescape=True,
)


def _valor_fmt(v: Decimal) -> str:
    """Decimal -> 'R$ 38.612,00' (milhar '.', decimal ',')."""
    inteiro = f"{v:,.2f}"  # 38,612.00 (estilo en)
    return "R$ " + inteiro.replace(",", "_").replace(".", ",").replace("_", ".")


def _data_fmt(d: dt.date | None) -> str:
    """date -> 'dd/mm/aaaa'; None -> '—' (padrão do projeto)."""
    return d.strftime("%d/%m/%Y") if d is not None else "—"


def _pagina(titulo: str, nome_cliente: str, corpo: str) -> str:
    """Embrulha um corpo JÁ renderizado (e já escapado) na shell base."""
    return _SHELL.render(titulo=titulo, nome_cliente=nome_cliente, corpo=corpo)


def _cel(valor: object, classe: str | None = None) -> dict:
    return {"valor": valor, "classe": classe}


def _gerar_lista(
    titulo: str,
    nome_cliente: str,
    cards: list[dict],
    colunas: list[str],
    linhas: list[list[dict]],
    vazio_msg: str,
) -> str:
    corpo = _CORPO_GENERICO.render(cards=cards, colunas=colunas, linhas=linhas, vazio_msg=vazio_msg)
    return _pagina(titulo, nome_cliente, corpo)


# ---------- PEDIDOS (saída byte-idêntica ao original) ----------
def _linha(p: Pedido) -> dict:
    pecas = [
        {"qtd": it.quantidade, "nome": it.sku.produto, "ref": it.sku.ref_produto} for it in p.itens
    ]
    return {
        "numero": p.id,
        "status": p.status.value,
        "pecas": pecas,
        "valor": _valor_fmt(p.valor_total),
        "data": p.data_pedido.strftime("%d/%m/%Y"),
    }


def gerar_html_pedidos(nome_cliente: str, pedidos: list[Pedido]) -> str:
    """Pedidos (já filtrados por cliente_id) -> página HTML autocontida."""
    total_pecas = sum(it.quantidade for p in pedidos for it in p.itens)
    valor_total = sum((p.valor_total for p in pedidos), Decimal("0"))
    corpo = _CORPO_PEDIDOS.render(
        total_pedidos=len(pedidos),
        total_pecas=total_pecas,
        valor_total=_valor_fmt(valor_total),
        linhas=[_linha(p) for p in pedidos],
    )
    return _pagina("Resumo de Pedidos", nome_cliente, corpo)


# ---------- NOTAS FISCAIS (posição de entrega é o destaque) ----------
def gerar_html_notas(nome_cliente: str, notas: list[NotaFiscal]) -> str:
    """Notas fiscais (já filtradas por cliente_id) -> página HTML autocontida."""
    colunas = ["Nº NF", "Emissão", "Valor", "Entrega", "Rastreio"]
    linhas = [
        [
            _cel(nf.numero_nf),
            _cel(_data_fmt(nf.data_emissao)),
            _cel(_valor_fmt(nf.valor_total)),
            _cel(nf.status_entrega.value, classe="status"),
            _cel(nf.codigo_rastreio or "—"),
        ]
        for nf in notas
    ]
    cards = [{"value": len(notas), "label": "Notas fiscais"}]
    return _gerar_lista(
        "Notas Fiscais",
        nome_cliente,
        cards,
        colunas,
        linhas,
        "Você ainda não tem nenhuma nota fiscal por aqui.",
    )


# ---------- TÍTULOS / FINANCEIRO (vencidos visíveis) ----------
def gerar_html_titulos(nome_cliente: str, titulos: list[Titulo]) -> str:
    """Títulos (já filtrados por cliente_id) -> página HTML autocontida."""
    colunas = ["Nº Título", "Parcela", "Valor", "Vencimento", "Status"]
    linhas = [
        [
            _cel(t.numero_titulo),
            _cel(t.parcela),
            _cel(_valor_fmt(t.valor)),
            _cel(_data_fmt(t.data_vencimento)),
            _cel(t.status.value, classe="status"),
        ]
        for t in titulos
    ]
    vencidos = sum(1 for t in titulos if t.status == StatusTitulo.vencido)
    cards = [
        {"value": len(titulos), "label": "Títulos"},
        {"value": vencidos, "label": "Vencidos"},
    ]
    return _gerar_lista(
        "Títulos",
        nome_cliente,
        cards,
        colunas,
        linhas,
        "Você não tem nenhum título por aqui.",
    )


# ---------- DEVOLUÇÕES (status + postagem + crédito) ----------
def _postagem_fmt(d: Devolucao) -> str:
    if d.codigo_postagem and d.prazo_postagem:
        return f"{d.codigo_postagem} (até {_data_fmt(d.prazo_postagem)})"
    if d.codigo_postagem:
        return d.codigo_postagem
    if d.prazo_postagem:
        return f"prazo {_data_fmt(d.prazo_postagem)}"
    return "—"


def gerar_html_devolucoes(nome_cliente: str, devolucoes: list[Devolucao]) -> str:
    """Devoluções (já filtradas por cliente_id) -> página HTML autocontida."""
    colunas = ["Nº Devolução", "Motivo", "Status", "Postagem", "Crédito"]
    linhas = [
        [
            _cel(d.numero_devolucao),
            _cel(d.motivo),
            _cel(d.status.value, classe="status"),
            _cel(_postagem_fmt(d)),
            _cel(_valor_fmt(d.valor_credito) if d.valor_credito is not None else "—"),
        ]
        for d in devolucoes
    ]
    cards = [{"value": len(devolucoes), "label": "Devoluções"}]
    return _gerar_lista(
        "Devoluções",
        nome_cliente,
        cards,
        colunas,
        linhas,
        "Você não tem nenhuma devolução por aqui.",
    )
