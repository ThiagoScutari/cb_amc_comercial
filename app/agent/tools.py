"""Ferramentas de leitura (a fronteira: o modelo PEDE, o código EXECUTA).

`Ferramentas` é construída com o `cliente_id` da SESSÃO (injetado pela Fase 3/4) —
o `cliente_id` NUNCA aparece no schema que o modelo vê. O modelo chama
`consultar_pedido(numero_pedido=4471)`; o código injeta `self.cliente_id`.

Views Pydantic são a borda de exposição: `EstoqueView` carrega SOMENTE `saldo`
(Q2) — `disponivel`/`reservado` não existem aqui, então não há como vazá-los.

O loop de tool-use com a Claude API (montar `tools=[...]`, despachar) é da Fase 4;
aqui ficam as implementações + views + permissão.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from pydantic import BaseModel

from app.data.models import Pedido, StatusPedido
from app.data.repository import DadosRepository


class PedidoItemView(BaseModel):
    sku: str
    produto: str
    cor: str
    tamanho: str
    quantidade: int
    preco_unitario: Decimal


class PedidoView(BaseModel):
    numero: int
    status: str
    faturado: bool
    data_prevista_entrega: dt.date | None
    valor_total: Decimal
    itens: list[PedidoItemView]

    @classmethod
    def from_model(cls, p: Pedido) -> PedidoView:
        return cls(
            numero=p.id,
            status=p.status.value,
            faturado=p.faturado,
            data_prevista_entrega=p.data_prevista_entrega,
            valor_total=p.valor_total,
            itens=[
                PedidoItemView(
                    sku=it.sku.sku,
                    produto=it.sku.produto,
                    cor=it.sku.cor,
                    tamanho=it.sku.tamanho,
                    quantidade=it.quantidade,
                    preco_unitario=it.preco_unitario,
                )
                for it in p.itens
            ],
        )


class PedidoResumo(BaseModel):
    numero: int
    status: str
    data_pedido: dt.date
    valor_total: Decimal


class ProdutoView(BaseModel):
    sku: str
    produto: str
    cor: str
    tamanho: str
    genero: str
    preco_tabela: Decimal


class EstoqueView(BaseModel):
    # SOMENTE `saldo` é exposto ao cliente (Q2). Sem `disponivel`/`reservado`.
    sku: str
    produto: str
    cor: str
    tamanho: str
    saldo: int


class NaoEncontrado(BaseModel):
    # Mesma resposta para "não existe" e "é de outro cliente" — não vaza existência.
    encontrado: bool = False
    mensagem: str = "Não encontrei esse pedido."


@dataclass
class Ferramentas:
    repo: DadosRepository
    cliente_id: int  # injetado pela SESSÃO (Fase 3/4) — NUNCA vem do modelo

    def consultar_pedido(self, numero_pedido: int) -> PedidoView | NaoEncontrado:
        ped = self.repo.consultar_pedido(self.cliente_id, numero_pedido)  # injeta cliente_id
        return PedidoView.from_model(ped) if ped is not None else NaoEncontrado()

    def listar_pedidos(self, filtro_status: str | None = None) -> list[PedidoResumo]:
        status = _status_ou_none(filtro_status)
        pedidos = self.repo.listar_pedidos(self.cliente_id, status)
        return [
            PedidoResumo(
                numero=p.id,
                status=p.status.value,
                data_pedido=p.data_pedido,
                valor_total=p.valor_total,
            )
            for p in pedidos
        ]

    def buscar_produto(self, texto_busca: str) -> list[ProdutoView]:
        return [
            ProdutoView(
                sku=p.sku,
                produto=p.produto,
                cor=p.cor,
                tamanho=p.tamanho,
                genero=p.genero,
                preco_tabela=p.preco_tabela,
            )
            for p in self.repo.buscar_produto(texto_busca)
        ]

    def consultar_disponibilidade(
        self,
        produto: str | None = None,
        tamanho: str | None = None,
        cor: str | None = None,
        sku: str | None = None,
    ) -> list[EstoqueView]:
        achados = self.repo.disponibilidade(produto=produto, tamanho=tamanho, cor=cor, sku=sku)
        # mapeia descartando disponivel/reservado: ao cliente, só `saldo`.
        return [
            EstoqueView(
                sku=prod.sku,
                produto=prod.produto,
                cor=prod.cor,
                tamanho=prod.tamanho,
                saldo=est.saldo,
            )
            for prod, est in achados
        ]


def _status_ou_none(valor: str | None) -> StatusPedido | None:
    if not valor:
        return None
    try:
        return StatusPedido(valor)
    except ValueError:
        return None
