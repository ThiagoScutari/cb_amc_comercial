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
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.data.catalogo import carregar_produtos
from app.data.db import criar_engine, criar_sessionmaker, recriar_schema
from app.data.models import (
    STATUS_FATURADOS,
    Cliente,
    Devolucao,
    Estoque,
    NotaFiscal,
    Pedido,
    PedidoItem,
    Produto,
    Solicitacao,
    StatusDevolucao,
    StatusEntrega,
    StatusPedido,
    StatusTitulo,
    TipoSolicitacao,
    Titulo,
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

# ── S12: entidades fiscais (NF/título/devolução), penduradas em pedidos FATURADOS ──
# Toda data sai de DATA_REF/data do pedido + timedelta — ZERO random/date.today() (regra de ouro).
_DIAS_EMISSAO_APOS_PEDIDO = 2  # NF emitida 2 dias após a data do pedido (faturamento)
_TITULO_BASE = 70001  # numero_titulo sequencial (string), sem colidir c/ pedidos/cadastro

# NFs do cliente-demo: uma por pedido FATURADO; status_entrega coerente com o status do pedido.
# (numero_nf, pedido, status_entrega, transportadora, codigo_rastreio, com_prevista, com_entrega)
_DEMO_NFS: list[tuple] = [
    (60001, 4473, StatusEntrega.emitida, None, None, False, False),
    (60002, 4474, StatusEntrega.coletada, None, None, False, False),
    (60003, 4475, StatusEntrega.em_transito, "Jadlog", "BR600030001BR", True, False),
    (60004, 4476, StatusEntrega.em_transito, "Correios", "BR600040001BR", True, False),
    (60005, 4477, StatusEntrega.entregue, "Correios", "BR600050001BR", True, True),
]
# Parcela (1-based) já PAGA por NF; o resto segue a regra de data (vencido/aberto).
_DEMO_TITULO_PAGO: dict[int, int] = {60001: 1}  # NF mais antiga: 1ª parcela paga

# Devoluções do cliente-demo cobrindo o lifecycle (penduradas em NFs do cliente 1).
# (numero, numero_nf, status, motivo, codigo_postagem, dias_prazo, dias_credito, dias_solicitacao)
_DEMO_DEVOLUCOES: list[tuple] = [
    (
        "80001",
        60001,
        StatusDevolucao.aguardando_postagem,
        "Tamanho divergente",
        "AA123456789BR",
        5,
        None,
        -2,
    ),
    (
        "80002",
        60002,
        StatusDevolucao.prazo_postagem_expirado,
        "Produto em desacordo",
        None,
        -3,
        None,
        -12,
    ),
    (
        "80003",
        60005,
        StatusDevolucao.credito_gerado,
        "Coleção trocada",  # devolução TOTAL -> crédito integral (= valor da NF)
        "BB987654321BR",
        -20,
        -5,
        -25,
    ),
]

# Cross-client (cliente 2, "à vista"): mínimo p/ o IDOR cross-client de S13 ter alvo real.
_XCLIENTE_NF = (60006, 4450, StatusEntrega.entregue, "Correios", "BR600060001BR")
_XCLIENTE_DEVOLUCAO = ("80004", 60006, StatusDevolucao.credito_gerado, "Desistência da compra")


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


def _parcelas_dias(condicao: str) -> list[int]:
    """Dias de vencimento por parcela a partir da condição comercial do cliente.

    "à vista" -> [0]; "28/35/42 dias" -> [28, 35, 42]; "30/60 dias" -> [30, 60].
    """
    nums = [int(t) for t in condicao.replace("dias", "").split("/") if t.strip().isdigit()]
    return nums or [0]


def criar_nota_fiscal(
    numero_nf: int,
    pedido: Pedido,
    status_entrega: StatusEntrega,
    *,
    transportadora: str | None = None,
    codigo_rastreio: str | None = None,
    com_prevista: bool = False,
    com_entrega: bool = False,
) -> NotaFiscal:
    """NF coerente e determinística. INVARIANTE: valor_total = pedido.valor_total.

    data_emissao = data do pedido + _DIAS_EMISSAO_APOS_PEDIDO (faturamento). As datas de
    entrega vêm do PRÓPRIO pedido (coerência com _OFFSETS). chave_acesso = numero_nf
    zero-padded a 44 díg. (sintética). id = numero_nf (PK inserível, igual a Pedido).
    """
    data_emissao = pedido.data_pedido + dt.timedelta(days=_DIAS_EMISSAO_APOS_PEDIDO)
    return NotaFiscal(
        id=numero_nf,
        numero_nf=numero_nf,
        cliente_id=pedido.cliente_id,
        pedido_id=pedido.id,
        data_emissao=data_emissao,
        chave_acesso=str(numero_nf).zfill(44),
        valor_total=pedido.valor_total,
        status_entrega=status_entrega,
        transportadora=transportadora,
        codigo_rastreio=codigo_rastreio,
        data_prevista_entrega=pedido.data_prevista_entrega if com_prevista else None,
        data_entrega=pedido.data_prevista_entrega if com_entrega else None,
    )


def criar_titulos(
    numero_base: int,
    nf: NotaFiscal,
    dias_parcelas: list[int],
    *,
    parcela_paga: int | None = None,
) -> list[Titulo]:
    """Parcelas de uma NF, determinísticas.

    INVARIANTE (centavo): Σ parcelas == nf.valor_total. As (n-1) primeiras parcelas são
    arredondadas a 2 casas (ROUND_HALF_UP); a ÚLTIMA absorve o residual — assim a soma
    fecha exatamente com o valor da NF mesmo quando não divide igual.

    Status por data: `parcela_paga` (1-based) -> pago (com data_pagamento); vencimento
    anterior a DATA_REF e não-paga -> vencido; senão em_aberto.
    """
    n = len(dias_parcelas)
    base = (nf.valor_total / n).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    valores = [base] * (n - 1) + [nf.valor_total - base * (n - 1)]
    titulos: list[Titulo] = []
    for i, (dias, valor) in enumerate(zip(dias_parcelas, valores, strict=True)):
        vencimento = nf.data_emissao + dt.timedelta(days=dias)
        if parcela_paga == i + 1:
            status = StatusTitulo.pago
            data_pagamento = nf.data_emissao + dt.timedelta(days=min(dias, 10))
        elif vencimento < DATA_REF:
            status = StatusTitulo.vencido
            data_pagamento = None
        else:
            status = StatusTitulo.em_aberto
            data_pagamento = None
        numero = numero_base + i
        titulos.append(
            Titulo(
                numero_titulo=str(numero),
                cliente_id=nf.cliente_id,
                nota_fiscal_id=nf.id,
                parcela=f"{i + 1}/{n}",
                valor=valor,
                data_vencimento=vencimento,
                status=status,
                data_pagamento=data_pagamento,
                linha_digitavel=str(numero).zfill(47),  # sintética (47 díg. estilo boleto)
            )
        )
    return titulos


def criar_devolucao(
    numero_devolucao: str,
    nf: NotaFiscal,
    status: StatusDevolucao,
    motivo: str,
    *,
    codigo_postagem: str | None = None,
    dias_prazo: int | None = None,
    valor_credito: Decimal | None = None,
    dias_credito: int | None = None,
    dias_solicitacao: int = 0,
) -> Devolucao:
    """Devolução determinística. Datas = DATA_REF + timedelta. `valor_credito` só no
    estado credito_gerado (>= 0, satisfaz o CHECK do schema)."""
    return Devolucao(
        numero_devolucao=numero_devolucao,
        cliente_id=nf.cliente_id,
        nota_fiscal_id=nf.id,
        motivo=motivo,
        status=status,
        codigo_postagem=codigo_postagem,
        prazo_postagem=(
            DATA_REF + dt.timedelta(days=dias_prazo) if dias_prazo is not None else None
        ),
        valor_credito=valor_credito,
        data_credito=(
            DATA_REF + dt.timedelta(days=dias_credito) if dias_credito is not None else None
        ),
        data_solicitacao=DATA_REF + dt.timedelta(days=dias_solicitacao),
    )


def _semear_fiscais(session: Session, ped_by_id: dict[int, Pedido]) -> None:
    """Passo 6 (S12): NFs (faturadas) -> títulos -> devoluções. Determinístico e FK-safe.

    Reusa os pedidos já persistidos (ped_by_id) — NÃO inventa SKU nem recalcula valores.
    """
    nf_by_numero: dict[int, NotaFiscal] = {}

    # 6a) NFs do cliente-demo + 1 NF cross-client (cliente 2)
    for numero_nf, ped_num, status_e, transp, rastreio, com_prev, com_ent in _DEMO_NFS:
        nf = criar_nota_fiscal(
            numero_nf,
            ped_by_id[ped_num],
            status_e,
            transportadora=transp,
            codigo_rastreio=rastreio,
            com_prevista=com_prev,
            com_entrega=com_ent,
        )
        session.add(nf)
        nf_by_numero[numero_nf] = nf
    x_num, x_ped, x_status, x_transp, x_rastreio = _XCLIENTE_NF
    nf_x = criar_nota_fiscal(
        x_num,
        ped_by_id[x_ped],
        x_status,
        transportadora=x_transp,
        codigo_rastreio=x_rastreio,
        com_entrega=True,
    )
    session.add(nf_x)
    nf_by_numero[x_num] = nf_x
    session.flush()

    # 6b) títulos: nº de parcelas vem da condição comercial do cliente (Σ parcelas == valor NF)
    cli_by_id = {c["id"]: c for c in _CLIENTES}
    prox_titulo = _TITULO_BASE
    for numero_nf, nf in nf_by_numero.items():
        dias = _parcelas_dias(cli_by_id[nf.cliente_id]["condicao_pagamento"])
        # "à vista" -> a única parcela já está paga; senão, só a NF marcada em _DEMO_TITULO_PAGO.
        paga = 1 if dias == [0] else _DEMO_TITULO_PAGO.get(numero_nf)
        titulos = criar_titulos(prox_titulo, nf, dias, parcela_paga=paga)
        session.add_all(titulos)
        prox_titulo += len(titulos)
    session.flush()

    # 6c) devoluções: lifecycle do cliente-demo + 1 cross-client
    for dev in _DEMO_DEVOLUCOES:
        numero, numero_nf, status, motivo, cod_post, dias_prazo, dias_cred, dias_sol = dev
        nf = nf_by_numero[numero_nf]
        # crédito INTEGRAL = valor_total da NF (devolução total), quantizado a 2 casas (>= 0).
        credito = nf.valor_total.quantize(Decimal("0.01")) if dias_cred is not None else None
        session.add(
            criar_devolucao(
                numero,
                nf,
                status,
                motivo,
                codigo_postagem=cod_post,
                dias_prazo=dias_prazo,
                valor_credito=credito,
                dias_credito=dias_cred,
                dias_solicitacao=dias_sol,
            )
        )
    xd_num, xd_nf_num, xd_status, xd_motivo = _XCLIENTE_DEVOLUCAO
    nf = nf_by_numero[xd_nf_num]
    session.add(
        criar_devolucao(
            xd_num,
            nf,
            xd_status,
            xd_motivo,
            codigo_postagem="CC111222333BR",
            dias_prazo=-15,
            valor_credito=nf.valor_total.quantize(Decimal("0.01")),  # crédito integral
            dias_credito=-8,
            dias_solicitacao=-30,
        )
    )
    session.flush()


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
    ped_by_id: dict[int, Pedido] = {}  # reusado pelo passo 6 (NF/título/devolução)
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
        ped_by_id[numero] = pedido
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

    # 6) entidades fiscais (S12): NF -> títulos -> devoluções (após os pedidos; FK-safe)
    _semear_fiscais(session, ped_by_id)


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
