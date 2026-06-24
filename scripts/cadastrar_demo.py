"""Cadastra um cliente-demo com dados coerentes, sob demanda (para a apresentação).

Uso (no host):
    docker compose exec app python -m scripts.cadastrar_demo \
        --telefone "5547999998888" --nome "Boutique do João"

Cada pessoa cadastrada vê SÓ os próprios pedidos — o anti-IDOR entre elas vira parte
da demo. REUSA a lógica coerente do seed (`criar_pedido`) — não duplica a invariante.

Determinístico (decisão A): todo cliente ganha o MESMO conjunto de 5 pedidos; muda só o
dono e a FAIXA de números (decisão B). Idempotente: re-run com o mesmo telefone ATUALIZA
o cliente e recria os mesmos 5 pedidos na MESMA faixa (não duplica). O estoque
(reservado/disponivel) não é tocado — é controle interno reversível e não-exposto (§6.1);
o bot só reporta `saldo`, que já é coerente (os SKUs usados são reais e já têm estoque).
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from decimal import Decimal

from app.data.db import criar_engine, criar_sessionmaker
from app.data.models import (
    STATUS_FATURADOS,
    Cliente,
    Devolucao,
    NotaFiscal,
    Pedido,
    Produto,
    Solicitacao,
    StatusDevolucao,
    StatusEntrega,
    StatusPedido,
    Titulo,
)
from app.data.repository import normalizar_telefone
from app.data.seed import (
    _itens_demo,
    _parcelas_dias,
    criar_devolucao,
    criar_nota_fiscal,
    criar_pedido,
    criar_titulos,
)
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

FAIXA_BASE = 5001  # acima do seed (4471–4479 e 4450–4467)
FAIXA_STEP = 10  # 1 bloco por cliente cadastrado (usa 5, sobra folga)

_CIDADE_PADRAO = "São Paulo/SP"
_CONDICAO_PADRAO = "28/35/42 dias"

# SKU real âncora (camiseta branca M; saldo 45 no seed) — liga "tem camiseta branca M?"
# ao pedido consultável da demo.
_SKU_CAMISETA = "340103413-M"

# Conjunto determinístico: (offset na faixa, status, papel na demo).
_TEMPLATE: list[tuple[int, StatusPedido, str]] = [
    (0, StatusPedido.em_analise, "cancelavel"),  # não-faturado -> "quero cancelar o X"
    (1, StatusPedido.confirmado, "consultavel"),  # "cadê meu pedido Y" (camiseta branca M)
    (2, StatusPedido.em_transito, "filler"),
    (3, StatusPedido.entregue, "filler"),
    (4, StatusPedido.faturado, "filler"),
]


@dataclass(frozen=True)
class ResumoCadastro:
    acao: str  # "criado" | "atualizado"
    nome: str
    telefone: str  # normalizado
    faixa_ini: int
    faixa_fim: int
    cancelavel: int
    consultavel: int

    def __str__(self) -> str:
        return (
            f"Cliente '{self.nome}' {self.acao} | tel {self.telefone} | "
            f"pedidos {self.faixa_ini}-{self.faixa_fim} | "
            f"CANCELÁVEL: {self.cancelavel} | "
            f"camiseta branca M CONSULTÁVEL no {self.consultavel}"
        )


def _catalogo(session: Session) -> tuple[dict[str, Produto], list[Produto]]:
    """Produtos EXISTENTES no banco (linhas reais, com id) — não recria o catálogo."""
    produtos = list(session.scalars(select(Produto)).all())
    return {p.sku: p for p in produtos}, sorted(produtos, key=lambda p: p.sku)


def _proxima_faixa(session: Session) -> int:
    maior = session.scalar(select(func.max(Pedido.id)).where(Pedido.id >= FAIXA_BASE))
    if maior is None:
        return FAIXA_BASE
    bloco = (maior - FAIXA_BASE) // FAIXA_STEP + 1
    return FAIXA_BASE + bloco * FAIXA_STEP


def _faixa_do_cliente(session: Session, cliente_id: int) -> int:
    menor = session.scalar(
        select(func.min(Pedido.id)).where(Pedido.cliente_id == cliente_id, Pedido.id >= FAIXA_BASE)
    )
    return menor if menor is not None else _proxima_faixa(session)


def _limpar_demo(session: Session, cliente_id: int, base: int) -> None:
    """Apaga pedidos + FISCAL da faixa do cliente, FK-safe (idempotência do cadastro, S17b).

    Ordem: solicitações + devoluções/títulos (referenciam NF) -> NFs (referenciam pedido) ->
    pedidos (cascade apaga itens). O cadastrado tem só ESTE bloco, então o fiscal é removido
    por cliente_id (não colide com o seed, que é de outros clientes).
    """
    ids = list(range(base, base + len(_TEMPLATE)))
    session.execute(
        delete(Solicitacao).where(
            Solicitacao.cliente_id == cliente_id, Solicitacao.pedido_id.in_(ids)
        )
    )
    session.execute(delete(Devolucao).where(Devolucao.cliente_id == cliente_id))
    session.execute(delete(Titulo).where(Titulo.cliente_id == cliente_id))
    session.execute(delete(NotaFiscal).where(NotaFiscal.cliente_id == cliente_id))
    for p in session.scalars(
        select(Pedido).where(Pedido.cliente_id == cliente_id, Pedido.id.in_(ids))
    ).all():
        session.delete(p)
    session.flush()


def _itens(papel: str, numero: int, produtos_ord: list[Produto]) -> list[tuple[str, int]]:
    """Grade engordada (S17b), reusando _itens_demo do seed (não duplica a regra). A camiseta
    âncora entra como FIXO nos papéis cancelável/consultável; o resto preenche 5–10 SKUs."""
    if papel == "cancelavel":
        return _itens_demo(numero, produtos_ord, fixos=[(_SKU_CAMISETA, 30)])
    if papel == "consultavel":
        return _itens_demo(numero, produtos_ord, fixos=[(_SKU_CAMISETA, 200)])
    return _itens_demo(numero, produtos_ord)


def _status_entrega(status: StatusPedido) -> StatusEntrega:
    """Status de entrega da NF coerente com o status do pedido (faturado -> emitida)."""
    if status == StatusPedido.entregue:
        return StatusEntrega.entregue
    if status in (StatusPedido.em_transito, StatusPedido.despachado):
        return StatusEntrega.em_transito
    if status == StatusPedido.em_separacao:
        return StatusEntrega.coletada
    return StatusEntrega.emitida


def _criar_fiscal(session: Session, pedidos: list[Pedido], base: int, condicao: str) -> None:
    """NF/título/devolução para o cliente cadastrado (S17b), reusando os helpers do seed.

    Numeração na faixa 90xxx por BLOCO do cliente — disjunta do seed (60/70/80xxx) e entre
    clientes; re-run no mesmo telefone reusa o MESMO bloco (idempotente via _limpar_demo).
    Determinismo aqui = valores batem entre si (NF=pedido, Σparcelas=NF, crédito=NF), NÃO
    reproduzir o mesmo banco (o cliente é autoincrement).
    """
    bloco = (base - FAIXA_BASE) // FAIXA_STEP
    faturados = [p for p in pedidos if p.status in STATUS_FATURADOS]
    nfs: list[NotaFiscal] = []
    for i, ped in enumerate(faturados):
        nf = criar_nota_fiscal(
            90000 + bloco * 10 + i,
            ped,
            _status_entrega(ped.status),
            com_prevista=ped.status in (StatusPedido.em_transito, StatusPedido.despachado),
            com_entrega=ped.status == StatusPedido.entregue,
        )
        session.add(nf)
        nfs.append(nf)
    session.flush()  # NFs têm id p/ os títulos/devoluções referenciarem
    # títulos: nº de parcelas vem da condição do cliente; mix de status (1ª NF com parcela 1 paga)
    dias = _parcelas_dias(condicao)
    prox_titulo = 91000 + bloco * 100
    for j, nf in enumerate(nfs):
        titulos = criar_titulos(prox_titulo, nf, dias, parcela_paga=1 if j == 0 else None)
        session.add_all(titulos)
        prox_titulo += len(titulos)
    # ao menos 1 devolução (crédito gerado) na 1ª NF
    if nfs:
        nf0 = nfs[0]
        session.add(
            criar_devolucao(
                f"{92000 + bloco * 10}",
                nf0,
                StatusDevolucao.credito_gerado,
                "Coleção trocada",
                codigo_postagem="DD111222333BR",
                dias_prazo=-15,
                valor_credito=nf0.valor_total.quantize(Decimal("0.01")),
                dias_credito=-8,
                dias_solicitacao=-30,
            )
        )


def cadastrar(
    session: Session,
    telefone: str,
    nome: str,
    *,
    cidade: str | None = None,
    condicao: str | None = None,
) -> ResumoCadastro:
    norm = normalizar_telefone(telefone)  # casa com resolver_sessao (Fase 3)
    if norm is None:
        raise ValueError(f"telefone inválido: {telefone!r}")
    prod_by_sku, produtos_ord = _catalogo(session)
    if not produtos_ord:
        raise RuntimeError("catálogo vazio — rode o seed antes (python -m app.data.seed).")
    if _SKU_CAMISETA not in prod_by_sku:
        raise RuntimeError(f"SKU âncora {_SKU_CAMISETA} ausente do catálogo.")

    cliente = session.scalar(select(Cliente).where(Cliente.telefone_whatsapp == norm))
    if cliente is not None:  # IDEMPOTENTE: atualiza, não duplica
        acao = "atualizado"
        cliente.nome_fantasia = nome
        cliente.razao_social = nome
        if cidade:
            cliente.cidade_uf = cidade
        if condicao:
            cliente.condicao_pagamento = condicao
        base = _faixa_do_cliente(session, cliente.id)
        _limpar_demo(session, cliente.id, base)  # recria na MESMA faixa
    else:
        acao = "criado"
        cliente = Cliente(
            razao_social=nome,
            nome_fantasia=nome,
            cnpj=("9" + norm)[:14],  # 14 díg., único por telefone; não colide com o seed
            telefone_whatsapp=norm,
            contato_nome=nome,
            cidade_uf=cidade or _CIDADE_PADRAO,
            condicao_pagamento=condicao or _CONDICAO_PADRAO,
        )
        session.add(cliente)
        session.flush()  # atribui id (auto, 11+) — sem colidir com 1..10 do seed
        base = _proxima_faixa(session)

    cancelavel = consultavel = base
    pedidos: list[Pedido] = []
    for offset, status, papel in _TEMPLATE:
        numero = base + offset
        itens = _itens(papel, numero, produtos_ord)  # grade engordada (S17b)
        ped = criar_pedido(numero, cliente.id, status, itens, prod_by_sku)
        session.add(ped)
        pedidos.append(ped)
        if papel == "cancelavel":
            cancelavel = numero
        elif papel == "consultavel":
            consultavel = numero
    session.flush()  # pedidos têm id; FK-safe para a NF
    _criar_fiscal(session, pedidos, base, cliente.condicao_pagamento)  # NF/título/devolução
    session.flush()
    return ResumoCadastro(
        acao, nome, norm, base, base + len(_TEMPLATE) - 1, cancelavel, consultavel
    )


def main(argv: list[str] | None = None) -> None:  # pragma: no cover - execução real (Postgres)
    parser = argparse.ArgumentParser(description="Cadastra um cliente-demo coerente sob demanda.")
    parser.add_argument("--telefone", required=True, help="telefone (qualquer formato BR)")
    parser.add_argument("--nome", required=True, help="nome fantasia da loja")
    parser.add_argument("--cidade", help=f"cidade/UF (default: {_CIDADE_PADRAO})")
    parser.add_argument("--condicao", help=f"condição de pagamento (default: {_CONDICAO_PADRAO})")
    args = parser.parse_args(argv)

    factory = criar_sessionmaker(criar_engine())
    with factory() as session:
        resumo = cadastrar(
            session, args.telefone, args.nome, cidade=args.cidade, condicao=args.condicao
        )
        session.commit()
    print(resumo)


if __name__ == "__main__":  # pragma: no cover
    main()
