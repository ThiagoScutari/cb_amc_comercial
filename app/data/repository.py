"""Repository (porta) + implementação Postgres mockada.

Fronteira mock→ERP (§6.4): o agente conversa com `DadosRepository`; hoje o
`MockRepository` lê o Postgres; amanhã um `ERPRepository` chama o ERP — sem tocar
no agente nem nos contratos.

SEGURANÇA (§2.3, §6.3): `cliente_id` é o 1º parâmetro OBRIGATÓRIO de toda consulta
de dado de cliente (pedidos/solicitações) — não há método que devolva pedido,
itens ou solicitação sem ele. Catálogo (produto/estoque) é GLOBAL: sem `cliente_id`
de propósito (ver produto de outrem não é vazamento). Itens só são alcançáveis via
`Pedido.itens` de um pedido já filtrado — NÃO existe `itens_por_pedido(pedido_id)`.
"""

from __future__ import annotations

from typing import Protocol

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.data.models import Cliente, Estoque, Pedido, Produto, Solicitacao, StatusPedido


def normalizar_telefone(raw: str | None) -> str | None:
    """Normaliza um telefone BR para a forma canônica `55 DDD 9XXXXXXXX` (13 díg).

    Aceita variações (com/sem +55, espaços, pontuação, com/sem 9º dígito) e as
    resolve para o MESMO valor — fechar essa porta dos fundos é anti-IDOR. Lixo /
    malformado → None (não casa com ninguém). Não decide política; só normaliza.
    """
    if not raw:
        return None
    d = "".join(c for c in raw if c.isdigit())
    if d.startswith("00"):  # prefixo internacional "00" -> remove
        d = d[2:]
    if not d.startswith("55"):
        if len(d) in (10, 11):  # nacional (DDD + 8/9 díg) -> assume BR
            d = "55" + d
        else:
            return None
    resto = d[2:]
    if len(resto) not in (10, 11):
        return None
    ddd, assinante = resto[:2], resto[2:]
    if len(assinante) == 8:  # sem 9º dígito (celular/WhatsApp) -> insere
        assinante = "9" + assinante
    return "55" + ddd + assinante


class DadosRepository(Protocol):
    # --- DADOS DO CLIENTE: cliente_id OBRIGATÓRIO (1º parâmetro, sem default) ---
    def consultar_pedido(self, cliente_id: int, numero_pedido: int) -> Pedido | None: ...
    def listar_pedidos(
        self, cliente_id: int, filtro_status: StatusPedido | None = None
    ) -> list[Pedido]: ...
    def listar_solicitacoes(self, cliente_id: int) -> list[Solicitacao]: ...

    # --- CATÁLOGO GLOBAL (compartilhado; SEM cliente_id — não é IDOR) ---
    def buscar_produto(self, texto_busca: str) -> list[Produto]: ...
    def disponibilidade(
        self,
        *,
        produto: str | None = None,
        tamanho: str | None = None,
        cor: str | None = None,
        sku: str | None = None,
    ) -> list[tuple[Produto, Estoque]]: ...

    # --- IDENTIDADE (dado puro p/ a auth da Fase 3) ---
    def cliente_por_telefone(self, telefone: str) -> Cliente | None: ...


class MockRepository:
    """Implementação sobre o Postgres mockado. Recebe a Session por requisição (G=A)."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def consultar_pedido(self, cliente_id: int, numero_pedido: int) -> Pedido | None:
        # Filtra por cliente_id: não pertence -> None (idêntico a inexistente; não vaza).
        return self.session.scalars(
            select(Pedido).where(
                Pedido.id == numero_pedido,
                Pedido.cliente_id == cliente_id,
            )
        ).one_or_none()

    def listar_pedidos(
        self, cliente_id: int, filtro_status: StatusPedido | None = None
    ) -> list[Pedido]:
        stmt = select(Pedido).where(Pedido.cliente_id == cliente_id).order_by(Pedido.id)
        if filtro_status is not None:
            stmt = stmt.where(Pedido.status == filtro_status)
        return list(self.session.scalars(stmt).all())

    def listar_solicitacoes(self, cliente_id: int) -> list[Solicitacao]:
        return list(
            self.session.scalars(
                select(Solicitacao)
                .where(Solicitacao.cliente_id == cliente_id)
                .order_by(Solicitacao.id)
            ).all()
        )

    def buscar_produto(self, texto_busca: str) -> list[Produto]:
        stmt = select(Produto).where(Produto.ativo)
        for token in (t for t in texto_busca.split() if t):
            like = f"%{token}%"
            stmt = stmt.where(
                or_(
                    Produto.produto.ilike(like),
                    Produto.cor.ilike(like),
                    Produto.tamanho.ilike(like),
                )
            )
        return list(self.session.scalars(stmt.order_by(Produto.sku).limit(50)).all())

    def disponibilidade(
        self,
        *,
        produto: str | None = None,
        tamanho: str | None = None,
        cor: str | None = None,
        sku: str | None = None,
    ) -> list[tuple[Produto, Estoque]]:
        stmt = select(Produto, Estoque).join(Estoque, Estoque.sku_id == Produto.id)
        if sku:
            stmt = stmt.where(Produto.sku == sku)
        else:
            if produto:
                stmt = stmt.where(Produto.produto.ilike(f"%{produto}%"))
            if cor:
                stmt = stmt.where(Produto.cor.ilike(f"%{cor}%"))
            if tamanho:
                stmt = stmt.where(Produto.tamanho == tamanho)
        stmt = stmt.order_by(Produto.sku).limit(50)
        return [(p, e) for p, e in self.session.execute(stmt).all()]

    def cliente_por_telefone(self, telefone: str) -> Cliente | None:
        # NÃO decide política: retorna Cliente|None. A decisão sobre None (escalar
        # para humano) é da Fase 3 (auth/session.py).
        norm = normalizar_telefone(telefone)
        if norm is None:
            return None
        return self.session.scalars(
            select(Cliente).where(Cliente.telefone_whatsapp == norm)
        ).one_or_none()
