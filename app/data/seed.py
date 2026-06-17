"""Seed determinístico do banco mockado (Fase 1c).

Produtos = catálogo real (fixture Colcci, via `carregar_produtos`); clientes,
pedidos, estoque e solicitações = sintéticos coerentes. Determinístico (sem
`random` nem `date.today()` em runtime) — a demo é reprodutível (MANIFESTO).

ESTOQUE (Q2): `saldo`, `disponivel` e `reservado` são campos SEPARADOS.
- `saldo` = baseline LIVRE, independente dos pedidos, >= 0 POR CONSTRUÇÃO
  (valores literais, nunca subtração). É o ÚNICO campo exposto ao cliente.
- `reservado` = Σ quantidade de itens em pedidos FATURADOS (travado p/ despacho).
- `disponivel` = Σ quantidade de itens em pedidos NÃO-faturados e NÃO-cancelados
  (reversível). Itens de pedidos CANCELADOS não entram em nenhum dos dois
  (o estoque "volta"); `Cancelamento solicitado` ainda conta em `disponivel`.

Como rodar: `python -m app.data.seed` (lê DATABASE_URL das settings; recria o
schema e popula). Os testes chamam `popular(session)` sobre SQLite in-memory.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.data.catalogo import carregar_produtos
from app.data.db import criar_engine, criar_sessionmaker, recriar_schema
from app.data.models import (
    STATUS_FATURADOS,
    Cliente,
    Estoque,
    Pedido,
    PedidoItem,
    Produto,
    Solicitacao,
    StatusPedido,
    TipoSolicitacao,
)

DATA_REF = dt.date(2026, 6, 16)  # âncora fixa (determinismo de demo)
DEMO_CLIENTE_ID = 1
DEMO_PHONE = "5531999990001"  # TODO Fase 8: trocar pelo número dedicado do WhatsApp

# offsets em dias por status: (data_pedido, data_prevista_entrega). None = sem prazo.
_OFFSETS: dict[StatusPedido, tuple[int, int | None]] = {
    StatusPedido.em_analise: (-3, 21),
    StatusPedido.confirmado: (-10, 12),
    StatusPedido.faturado: (-15, 8),
    StatusPedido.em_separacao: (-18, 5),
    StatusPedido.despachado: (-22, 3),
    StatusPedido.em_transito: (-25, 2),
    StatusPedido.entregue: (-40, -25),  # mês passado -> cobre "e o do mês passado?"
    StatusPedido.cancelamento_solicitado: (-8, 14),
    StatusPedido.cancelado: (-30, None),
}

# Pedidos do cliente-demo: um por status (4471 = Confirmado, cancelável; cobre §10).
_DEMO_PEDIDOS: list[tuple[int, StatusPedido]] = [
    (4471, StatusPedido.confirmado),
    (4472, StatusPedido.em_analise),
    (4473, StatusPedido.faturado),
    (4474, StatusPedido.em_separacao),
    (4475, StatusPedido.despachado),
    (4476, StatusPedido.em_transito),
    (4477, StatusPedido.entregue),
    (4478, StatusPedido.cancelamento_solicitado),
    (4479, StatusPedido.cancelado),  # faturado->cancelado: itens NÃO entram no estoque
]
# Itens fixos de demo (SKUs reais do fixture); os demais pedidos usam filler por índice.
_DEMO_ITENS: dict[int, list[tuple[str, int]]] = {
    4471: [("340103413-M", 200)],  # camiseta branca M (cancelar/«já saiu?»/«tem ...?»)
    4479: [("10125173-42", 100)],  # calça preta 42 — caso cancelado
}

# Overrides de saldo p/ coerência da demo (§10). Demais SKUs: _saldo_baseline.
_SALDO_DEMO: dict[str, int] = {
    "340103413-M": 45,  # camiseta branca M — comprável ("tem pra comprar?")
    "10125173-42": 3,  # calça preta 42 — estoque baixo (urgência)
    "380103554-M": 0,  # kit regata M — sold-out ("não tem")
}

_CLIENTES: list[dict] = [
    {
        "id": 1,
        "razao_social": "Boutique Aurora Comércio de Roupas LTDA",
        "nome_fantasia": "Boutique Aurora",
        "cnpj": "11222333000181",
        "telefone_whatsapp": DEMO_PHONE,
        "contato_nome": "Marina Prado",
        "cidade_uf": "Belo Horizonte/MG",
        "condicao_pagamento": "28/35/42 dias",
    },
    {
        "id": 2,
        "razao_social": "Maré Alta Moda Praia LTDA",
        "nome_fantasia": "Maré Alta Store",
        "cnpj": "22333444000172",
        "telefone_whatsapp": "5531988880002",
        "contato_nome": "RafaelNunes",
        "cidade_uf": "Vitória/ES",
        "condicao_pagamento": "à vista",
    },
    {
        "id": 3,
        "razao_social": "Estilo Urbano Confecções LTDA",
        "nome_fantasia": "Estilo Urbano",
        "cnpj": "33444555000163",
        "telefone_whatsapp": "5511977770003",
        "contato_nome": "Camila Souza",
        "cidade_uf": "São Paulo/SP",
        "condicao_pagamento": "30/60 dias",
    },
    {
        "id": 4,
        "razao_social": "Loja do Sol Vestuário EIRELI",
        "nome_fantasia": "Loja do Sol",
        "cnpj": "44555666000154",
        "telefone_whatsapp": "5585966660004",
        "contato_nome": "Bruno Carvalho",
        "cidade_uf": "Fortaleza/CE",
        "condicao_pagamento": "28/35/42 dias",
    },
    {
        "id": 5,
        "razao_social": "Vitrine Sul Comércio de Confecções LTDA",
        "nome_fantasia": "Vitrine Sul",
        "cnpj": "55666777000145",
        "telefone_whatsapp": "5551955550005",
        "contato_nome": "Letícia Ramos",
        "cidade_uf": "Porto Alegre/RS",
        "condicao_pagamento": "à vista",
    },
    {
        "id": 6,
        "razao_social": "Charme & Cia Modas LTDA",
        "nome_fantasia": "Charme & Cia",
        "cnpj": "66777888000136",
        "telefone_whatsapp": "5562944440006",
        "contato_nome": "Diego Faria",
        "cidade_uf": "Goiânia/GO",
        "condicao_pagamento": "30/60 dias",
    },
    {
        "id": 7,
        "razao_social": "Atelier da Moda Comércio LTDA",
        "nome_fantasia": "Atelier da Moda",
        "cnpj": "77888999000127",
        "telefone_whatsapp": "5571933330007",
        "contato_nome": "Patrícia Lopes",
        "cidade_uf": "Salvador/BA",
        "condicao_pagamento": "28/35/42 dias",
    },
    {
        "id": 8,
        "razao_social": "Norte Fashion Distribuidora LTDA",
        "nome_fantasia": "Norte Fashion",
        "cnpj": "88999000000118",
        "telefone_whatsapp": "5591922220008",
        "contato_nome": "Gustavo Pinto",
        "cidade_uf": "Belém/PA",
        "condicao_pagamento": "à vista",
    },
    {
        "id": 9,
        "razao_social": "Bella Vita Boutique LTDA",
        "nome_fantasia": "Bella Vita",
        "cnpj": "99000111000109",
        "telefone_whatsapp": "5547911110009",
        "contato_nome": "Fernanda Dias",
        "cidade_uf": "Blumenau/SC",
        "condicao_pagamento": "30/60 dias",
    },
    {
        "id": 10,
        "razao_social": "Capital Modas Comércio LTDA",
        "nome_fantasia": "Capital Modas",
        "cnpj": "10111213000191",
        "telefone_whatsapp": "5561900000010",
        "contato_nome": "Thiago Martins",
        "cidade_uf": "Brasília/DF",
        "condicao_pagamento": "28/35/42 dias",
    },
]

# Ciclo de status p/ os pedidos dos demais clientes (cobre faturados e não-faturados).
_CICLO_OUTROS = [
    StatusPedido.entregue,
    StatusPedido.confirmado,
    StatusPedido.faturado,
    StatusPedido.despachado,
    StatusPedido.em_analise,
    StatusPedido.em_transito,
]


def _saldo_baseline(i: int) -> int:
    """Baseline de saldo livre, determinístico por índice e >= 0 por construção.

    ~10% sold-out (0), ~20% baixo (2-3, urgência na demo), ~70% confortável (15-74).
    """
    r = i % 10
    if r == 0:
        return 0
    if r == 1:
        return 2
    if r == 2:
        return 3
    return 15 + (i * 7) % 60


def _plano_pedidos(sku_idx) -> list[tuple[int, int, StatusPedido, list[tuple[str, int]]]]:
    """(numero, cliente_id, status, [(sku, quantidade)]) — determinístico."""
    planos: list[tuple[int, int, StatusPedido, list[tuple[str, int]]]] = []
    # cliente-demo: um pedido por status
    for i, (numero, status) in enumerate(_DEMO_PEDIDOS):
        itens = _DEMO_ITENS.get(numero) or [(sku_idx(17 + i * 13), 6 + i)]
        planos.append((numero, DEMO_CLIENTE_ID, status, itens))
    # demais clientes (id 2..10): 2 pedidos cada, números 4450..4467
    numero = 4450
    k = 0
    for cliente in _CLIENTES:
        if cliente["id"] == DEMO_CLIENTE_ID:
            continue
        for _ in range(2):
            status = _CICLO_OUTROS[k % len(_CICLO_OUTROS)]
            itens = [(sku_idx(k * 9 + 3), 4 + (k % 5))]
            planos.append((numero, cliente["id"], status, itens))
            numero += 1
            k += 1
    return planos


def criar_pedido(
    numero: int,
    cliente_id: int,
    status: StatusPedido,
    itens: list[tuple[str, int]],
    prod_by_sku: dict[str, Produto],
) -> Pedido:
    """Monta um Pedido COERENTE: datas por status (_OFFSETS) e
    valor_total = Σ(quantidade × preco_tabela). Fonte ÚNICA da invariante —
    reusada por popular() (seed) e pelo cadastro de demo sob demanda."""
    dp, dpe = _OFFSETS[status]
    pedido = Pedido(
        id=numero,
        cliente_id=cliente_id,
        status=status,
        data_pedido=DATA_REF + dt.timedelta(days=dp),
        data_prevista_entrega=(DATA_REF + dt.timedelta(days=dpe)) if dpe is not None else None,
        valor_total=Decimal("0"),
    )
    total = Decimal("0")
    for sku, qtd in itens:
        prod = prod_by_sku[sku]
        pedido.itens.append(
            PedidoItem(sku_id=prod.id, quantidade=qtd, preco_unitario=prod.preco_tabela)
        )
        total += qtd * prod.preco_tabela
    pedido.valor_total = total
    return pedido


def _sincronizar_sequence_clientes(session: Session) -> None:
    """Avança a sequence de `clientes.id` após inserts com id EXPLÍCITO (1..10).

    No Postgres, inserir um id explícito numa coluna serial NÃO move a sequence;
    o próximo insert AUTO (ex.: cadastrar_demo) tentaria id=1 e colidiria com o
    seed (UniqueViolation em clientes_pkey). Aqui realinhamos a sequence ao
    MAX(id) corrente. No-op em SQLite (sem sequence; o ROWID já usa max+1) — por
    isso o bug só aparece em Postgres, e o teste de regressão roda lá (§A1).
    """
    if session.bind.dialect.name != "postgresql":
        return
    session.execute(
        text(
            "SELECT setval(pg_get_serial_sequence('clientes', 'id'), "
            "(SELECT MAX(id) FROM clientes))"
        )
    )


def popular(session: Session) -> None:
    """Popula todas as tabelas em ordem FK-safe, coerente e determinística."""
    # 1) clientes (ids explícitos 1..10) + realinhamento da sequence (anti-colisão)
    session.add_all(Cliente(**c) for c in _CLIENTES)
    session.flush()
    _sincronizar_sequence_clientes(session)

    # 2) produtos (catálogo real, do fixture)
    produtos = carregar_produtos()
    session.add_all(produtos)
    session.flush()
    prod_by_sku = {p.sku: p for p in produtos}
    produtos_ord = sorted(produtos, key=lambda p: p.sku)

    def sku_idx(i: int) -> str:
        return produtos_ord[i % len(produtos_ord)].sku

    # 3) pedidos + itens (valor_total = soma dos itens) e acúmulo p/ estoque
    reservado: dict[int, int] = defaultdict(int)
    disponivel: dict[int, int] = defaultdict(int)
    for numero, cliente_id, status, itens in _plano_pedidos(sku_idx):
        pedido = criar_pedido(numero, cliente_id, status, itens, prod_by_sku)
        # bucket de estoque: faturado->reservado; não-faturado e não-cancelado->disponivel.
        if status in STATUS_FATURADOS:
            bucket = reservado
        elif status != StatusPedido.cancelado:
            bucket = disponivel
        else:
            bucket = None  # cancelado: itens "voltam" — não entram em nenhum
        if bucket is not None:
            for it in pedido.itens:
                bucket[it.sku_id] += it.quantidade
        session.add(pedido)
    session.flush()

    # 4) estoque (uma linha por SKU; saldo independente e >= 0 por construção)
    for i, prod in enumerate(produtos_ord):
        saldo = _SALDO_DEMO.get(prod.sku, _saldo_baseline(i))
        session.add(
            Estoque(
                sku_id=prod.id,
                saldo=saldo,
                disponivel=disponivel[prod.id],
                reservado=reservado[prod.id],
            )
        )

    # 5) solicitação pendente (cliente-demo; pedido_id pertence a ele — anti-IDOR)
    session.add(
        Solicitacao(
            cliente_id=DEMO_CLIENTE_ID,
            tipo=TipoSolicitacao.cancelamento,
            pedido_id=4478,
            payload={"motivo": "cliente pediu cancelamento por engano no tamanho"},
        )
    )
    session.flush()


def main() -> None:  # pragma: no cover - caminho de execução real (Postgres)
    engine = criar_engine()
    recriar_schema(engine)
    factory = criar_sessionmaker(engine)
    with factory() as session:
        popular(session)
        session.commit()
    print("seed concluído.")


if __name__ == "__main__":  # pragma: no cover
    main()
