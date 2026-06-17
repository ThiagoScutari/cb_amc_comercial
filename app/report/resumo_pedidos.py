"""Resumo visual dos pedidos do cliente em HTML (diferencial da demo). SEM REDE/DISCO.

Função pura: recebe os pedidos JÁ FILTRADOS por cliente_id (listar_pedidos filtra —
anti-IDOR) e devolve uma página HTML autocontida. O design (tema escuro, cards, tabela,
mobile-first) reusa o do chatbot_sheet_talk, SEM Chart.js/CDN — renderiza offline.

Jinja2 com autoescape ON: nome do cliente e dados de produto nunca injetam HTML.
É ADITIVO no fluxo (router.py): se gerar/enviar falhar, o bot já respondeu em texto.
"""

from __future__ import annotations

from decimal import Decimal

from jinja2 import Template

from app.data.models import Pedido

# CSS reaproveitado do dashboard_service.py do chatbot_sheet_talk (tema escuro, cards,
# tabela). Sem <script>/CDN: a página abre offline no navegador do celular.
_TEMPLATE = Template(
    """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Resumo de Pedidos — {{ nome_cliente }}</title>
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
<h1>Resumo de Pedidos</h1>
<div class="sub">{{ nome_cliente }}</div>

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
</div>
</body>
</html>""",
    autoescape=True,
)


def _valor_fmt(v: Decimal) -> str:
    """Decimal -> 'R$ 38.612,00' (milhar '.', decimal ',')."""
    inteiro = f"{v:,.2f}"  # 38,612.00 (estilo en)
    return "R$ " + inteiro.replace(",", "_").replace(".", ",").replace("_", ".")


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
    return _TEMPLATE.render(
        nome_cliente=nome_cliente,
        total_pedidos=len(pedidos),
        total_pecas=total_pecas,
        valor_total=_valor_fmt(valor_total),
        linhas=[_linha(p) for p in pedidos],
    )
