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

from decimal import Decimal
from typing import Protocol

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.data.models import (
    Cliente,
    Devolucao,
    Estoque,
    NotaFiscal,
    Pedido,
    Produto,
    Solicitacao,
    StatusPedido,
    StatusTitulo,
    TipoSolicitacao,
    Titulo,
)


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
    def dados_cliente(self, cliente_id: int) -> Cliente | None: ...

    # --- DADOS FISCAIS / FINANCEIROS (S13, read-only): cliente_id 1º param obrigatório ---
    def consultar_nota_fiscal(self, cliente_id: int, numero_nf: int) -> NotaFiscal | None: ...
    def consultar_titulo(self, cliente_id: int, numero_titulo: str) -> Titulo | None: ...
    def consultar_devolucao(self, cliente_id: int, numero_devolucao: str) -> Devolucao | None: ...
    def listar_notas_fiscais(self, cliente_id: int) -> list[NotaFiscal]: ...
    def listar_titulos(
        self, cliente_id: int, filtro_status: StatusTitulo | None = None
    ) -> list[Titulo]: ...
    def listar_devolucoes(self, cliente_id: int) -> list[Devolucao]: ...
    def consultar_faturamento(self, cliente_id: int) -> dict: ...

    # --- ESCRITA (intake): só REGISTRA, NÃO muta pedido/estoque ---
    def registrar_cancelamento(
        self, cliente_id: int, numero_pedido: int, motivo: str | None = None
    ) -> Solicitacao | None: ...
    def registrar_compra(self, cliente_id: int, itens: list[dict]) -> Solicitacao: ...

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

    def dados_cliente(self, cliente_id: int) -> Cliente | None:
        # Filtra pelo cliente_id da sessão: estruturalmente impossível ler outro cliente
        # (o tool não tem parâmetro; o id vem do código — anti-IDOR, §2.3).
        return self.session.scalars(select(Cliente).where(Cliente.id == cliente_id)).one_or_none()

    # --- DADOS FISCAIS / FINANCEIROS (S13): read-only, filtra DIRETO pela coluna cliente_id ---
    def consultar_nota_fiscal(self, cliente_id: int, numero_nf: int) -> NotaFiscal | None:
        # NF carrega cliente_id próprio (S11): filtro DIRETO, igual a consultar_pedido.
        # Não pertence (ou inexiste) -> None (idêntico; não vaza existência).
        return self.session.scalars(
            select(NotaFiscal).where(
                NotaFiscal.numero_nf == numero_nf,
                NotaFiscal.cliente_id == cliente_id,
            )
        ).one_or_none()

    def consultar_titulo(self, cliente_id: int, numero_titulo: str) -> Titulo | None:
        return self.session.scalars(
            select(Titulo).where(
                Titulo.numero_titulo == numero_titulo,
                Titulo.cliente_id == cliente_id,
            )
        ).one_or_none()

    def consultar_devolucao(self, cliente_id: int, numero_devolucao: str) -> Devolucao | None:
        return self.session.scalars(
            select(Devolucao).where(
                Devolucao.numero_devolucao == numero_devolucao,
                Devolucao.cliente_id == cliente_id,
            )
        ).one_or_none()

    def listar_notas_fiscais(self, cliente_id: int) -> list[NotaFiscal]:
        return list(
            self.session.scalars(
                select(NotaFiscal)
                .where(NotaFiscal.cliente_id == cliente_id)
                .order_by(NotaFiscal.numero_nf)  # ordem estável (determinismo de saída)
            ).all()
        )

    def listar_titulos(
        self, cliente_id: int, filtro_status: StatusTitulo | None = None
    ) -> list[Titulo]:
        # Espelha listar_pedidos: filtro opcional por status, sempre filtrado por cliente_id.
        stmt = (
            select(Titulo)
            .where(Titulo.cliente_id == cliente_id)
            .order_by(Titulo.data_vencimento, Titulo.numero_titulo)
        )
        if filtro_status is not None:
            stmt = stmt.where(Titulo.status == filtro_status)
        return list(self.session.scalars(stmt).all())

    def listar_devolucoes(self, cliente_id: int) -> list[Devolucao]:
        return list(
            self.session.scalars(
                select(Devolucao)
                .where(Devolucao.cliente_id == cliente_id)
                .order_by(Devolucao.data_solicitacao, Devolucao.numero_devolucao)
            ).all()
        )

    def consultar_faturamento(self, cliente_id: int) -> dict:
        """Agregado read-only: quantos pedidos do cliente viraram NF (e quanto em R$).

        "Tem NF" = existe NotaFiscal com aquele pedido_id E o MESMO cliente_id. Carrega
        só os pedidos do PRÓPRIO cliente (escopo pequeno) + os pedido_id com NF — soma
        exata em Decimal, sem varrer o banco inteiro. Tudo filtrado por cliente_id.
        """
        pedidos = self.session.scalars(select(Pedido).where(Pedido.cliente_id == cliente_id)).all()
        com_nf = set(
            self.session.scalars(
                select(NotaFiscal.pedido_id).where(NotaFiscal.cliente_id == cliente_id)
            ).all()
        )
        faturados = [p for p in pedidos if p.id in com_nf]
        a_faturar = [p for p in pedidos if p.id not in com_nf]
        return {
            "pedidos_total": len(pedidos),
            "pedidos_faturados": len(faturados),
            "pedidos_a_faturar": len(a_faturar),
            "valor_faturado": sum((p.valor_total for p in faturados), Decimal("0")),
            "valor_a_faturar": sum((p.valor_total for p in a_faturar), Decimal("0")),
        }

    def cliente_por_telefone(self, telefone: str) -> Cliente | None:
        # NÃO decide política: retorna Cliente|None. A decisão sobre None (escalar
        # para humano) é da Fase 3 (auth/session.py).
        norm = normalizar_telefone(telefone)
        if norm is None:
            return None
        return self.session.scalars(
            select(Cliente).where(Cliente.telefone_whatsapp == norm)
        ).one_or_none()

    # --- ESCRITA (intake) ---
    def registrar_cancelamento(
        self, cliente_id: int, numero_pedido: int, motivo: str | None = None
    ) -> Solicitacao | None:
        # Anti-IDOR de ESCRITA: só registra se o pedido é do cliente da sessão.
        # Não pertence (ou inexiste) -> None e NADA registrado. NÃO muta o pedido.
        if self.consultar_pedido(cliente_id, numero_pedido) is None:
            return None
        sol = Solicitacao(
            cliente_id=cliente_id,
            tipo=TipoSolicitacao.cancelamento,
            pedido_id=numero_pedido,
            payload={"motivo": motivo},
        )
        self.session.add(sol)
        self.session.flush()  # atribui id; o request comita (Fase 8) / rollback em erro
        return sol

    def registrar_compra(self, cliente_id: int, itens: list[dict]) -> Solicitacao:
        # Compra é pedido do PRÓPRIO cliente (sem recurso cruzado): cliente_id da sessão.
        # Enriquece com snapshot do produto p/ o humano; sku desconhecido é anotado,
        # não bloqueia (intake). NÃO toca em estoque.
        enriquecidos = []
        for item in itens:
            sku = item.get("sku")
            prod = (
                self.session.scalars(select(Produto).where(Produto.sku == sku)).one_or_none()
                if sku
                else None
            )
            enriquecidos.append(
                {
                    "sku": sku,
                    "quantidade": item.get("quantidade"),
                    "produto": prod.produto if prod else None,
                    "preco_tabela": str(prod.preco_tabela) if prod else None,
                    "encontrado": prod is not None,
                }
            )
        sol = Solicitacao(
            cliente_id=cliente_id,
            tipo=TipoSolicitacao.compra,
            payload={"itens": enriquecidos},
        )
        self.session.add(sol)
        self.session.flush()
        return sol
