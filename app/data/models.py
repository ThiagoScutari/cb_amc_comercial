"""Modelos SQLAlchemy 2.x do schema mockado (spec §5).

Schema-first: esta é a fonte da verdade do MVP. Tipagem forte via `Mapped`.
Modelado para que a troca futura pelo ERP real (§6.4) seja só trocar a camada
de dados, sem tocar nos contratos.

Decisões aplicadas (com o arquiteto):
- Sem coluna booleana `faturado`: ele é DERIVADO de `StatusPedido`
  (`Pedido.faturado`, hybrid_property) — fonte única de verdade.
- `pedidos.id` é PK inteira INSERÍVEL (`autoincrement=False`): o seed (1c)
  atribui números realistas.
- Enums como VARCHAR + CHECK (`native_enum=False`, A3) — portável p/ SQLite/PG.

CONTRATOS para fases seguintes (NÃO violar):
- [Fase 2 / A2] O repository NÃO exporá método que retorne `pedido_itens` por
  `pedido_id` sem antes validar que o pedido é do cliente da sessão. Itens só
  via `Pedido.itens` (relationship) de um pedido já filtrado por `cliente_id`.
  Haverá teste de IDOR explícito (cliente A tentando ver itens de pedido de B
  → vazio/negado).
- [Fase 2 / A1] Os testes de IDOR rodam contra Postgres real (não SQLite).
- [Fase 5] `solicitacoes.pedido_id` deve ser validado como pertencente ao
  `solicitacoes.cliente_id` ANTES de aceitar um cancelamento (anti-IDOR no
  caminho de escrita).
- [Q2 / Fase 2] Só `estoque.saldo` é exposto ao cliente; `disponivel`/`reservado`
  são internos (o `EstoqueView` da Fase 2 carrega APENAS `saldo`).
- [Fase 1c / seed] Coerência obrigatória: `pedidos.valor_total` = soma dos itens;
  e `estoque.saldo/disponivel/reservado` consistentes por SKU
  (não-faturado→disponivel; faturado→reservado; resto→saldo).
"""

import datetime as dt
import enum
from decimal import Decimal

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class StatusPedido(str, enum.Enum):
    """Ciclo de status (spec §5.3), incluindo os ramos de cancelamento."""

    em_analise = "Em análise"
    confirmado = "Confirmado"
    faturado = "Faturado"
    em_separacao = "Em separação"
    despachado = "Despachado"
    em_transito = "Em trânsito"
    entregue = "Entregue"
    cancelamento_solicitado = "Cancelamento solicitado"
    cancelado = "Cancelado"


class TipoSolicitacao(str, enum.Enum):
    cancelamento = "cancelamento"
    compra = "compra"


class StatusSolicitacao(str, enum.Enum):
    pendente = "pendente"


# Um pedido está "faturado" a partir do status Faturado (divisor disponível↔reservado,
# spec §5.4). Os ramos de cancelamento NÃO contam como faturado no mock.
STATUS_FATURADOS: frozenset[StatusPedido] = frozenset(
    {
        StatusPedido.faturado,
        StatusPedido.em_separacao,
        StatusPedido.despachado,
        StatusPedido.em_transito,
        StatusPedido.entregue,
    }
)


def parse_ref_produto(ref: str) -> tuple[str, str, str]:
    """Quebra o RefId Colcci de 9 dígitos em (categoria_cod, marca_cod, ordem).

    Ex.: "360118439" -> ("36", "01", "18439"). Levanta ValueError se o formato
    não bater (9 dígitos numéricos).
    """
    if len(ref) != 9 or not ref.isdigit():
        raise ValueError(f"ref_produto inválido: {ref!r} (esperado 9 dígitos)")
    return ref[:2], ref[2:4], ref[4:9]


class Cliente(Base):
    __tablename__ = "clientes"

    id: Mapped[int] = mapped_column(primary_key=True)
    razao_social: Mapped[str] = mapped_column(String(120))
    nome_fantasia: Mapped[str] = mapped_column(String(120))
    cnpj: Mapped[str] = mapped_column(String(14), unique=True)
    # chave de autenticação (Q1): 1 número = 1 cliente.
    telefone_whatsapp: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    contato_nome: Mapped[str] = mapped_column(String(120))
    cidade_uf: Mapped[str] = mapped_column(String(60))
    condicao_pagamento: Mapped[str] = mapped_column(String(60))
    ativo: Mapped[bool] = mapped_column(default=True)

    pedidos: Mapped[list["Pedido"]] = relationship(back_populates="cliente")
    solicitacoes: Mapped[list["Solicitacao"]] = relationship(back_populates="cliente")


class Produto(Base):
    """1 linha = 1 SKU (produto × tamanho × cor). Catálogo Colcci — global."""

    __tablename__ = "produtos"

    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(String(20), unique=True, index=True)  # "360118439-M"
    ref_produto: Mapped[str] = mapped_column(String(9), index=True)  # RefId VTEX
    categoria_cod: Mapped[str] = mapped_column(String(2))  # derivado do ref
    marca_cod: Mapped[str] = mapped_column(String(2))  # derivado do ref
    ordem: Mapped[str] = mapped_column(String(5))  # derivado do ref
    produto: Mapped[str] = mapped_column(String(120))
    tamanho: Mapped[str] = mapped_column(String(4))
    cor: Mapped[str] = mapped_column(String(40))
    preco_tabela: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    ativo: Mapped[bool] = mapped_column(default=True)

    estoque: Mapped["Estoque"] = relationship(back_populates="produto", uselist=False)
    itens: Mapped[list["PedidoItem"]] = relationship(back_populates="sku")


class Pedido(Base):
    __tablename__ = "pedidos"

    # PK inteira INSERÍVEL (não Identity always): o seed atribui números realistas.
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    # Âncora anti-IDOR (princípio 2): toda query de pedido filtra por cliente_id.
    cliente_id: Mapped[int] = mapped_column(ForeignKey("clientes.id"), index=True)
    data_pedido: Mapped[dt.date] = mapped_column(Date)
    status: Mapped[StatusPedido] = mapped_column(Enum(StatusPedido, native_enum=False))
    data_prevista_entrega: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    valor_total: Mapped[Decimal] = mapped_column(Numeric(12, 2))

    cliente: Mapped["Cliente"] = relationship(back_populates="pedidos")
    itens: Mapped[list["PedidoItem"]] = relationship(
        back_populates="pedido", cascade="all, delete-orphan"
    )

    @hybrid_property
    def faturado(self) -> bool:
        """Derivado do status (sem coluna booleana redundante)."""
        return self.status in STATUS_FATURADOS

    @faturado.inplace.expression
    @classmethod
    def _faturado_expr(cls):
        return cls.status.in_(STATUS_FATURADOS)


class PedidoItem(Base):
    """Sem cliente_id: isolamento transitivo via `pedido` (contrato A2)."""

    __tablename__ = "pedido_itens"

    id: Mapped[int] = mapped_column(primary_key=True)
    pedido_id: Mapped[int] = mapped_column(ForeignKey("pedidos.id"), index=True)
    sku_id: Mapped[int] = mapped_column(ForeignKey("produtos.id"), index=True)
    quantidade: Mapped[int] = mapped_column(Integer)
    preco_unitario: Mapped[Decimal] = mapped_column(Numeric(10, 2))

    pedido: Mapped["Pedido"] = relationship(back_populates="itens")
    sku: Mapped["Produto"] = relationship(back_populates="itens")


class Estoque(Base):
    """Estoque por SKU (global). saldo é exposto; disponivel/reservado são internos."""

    __tablename__ = "estoque"

    sku_id: Mapped[int] = mapped_column(ForeignKey("produtos.id"), primary_key=True)
    saldo: Mapped[int] = mapped_column(Integer, default=0)  # EXPOSTO ao cliente (Q2)
    disponivel: Mapped[int] = mapped_column(Integer, default=0)  # interno, reversível
    reservado: Mapped[int] = mapped_column(Integer, default=0)  # interno (faturado)

    __table_args__ = (
        CheckConstraint(
            "saldo >= 0 AND disponivel >= 0 AND reservado >= 0",
            name="ck_estoque_nao_negativo",
        ),
    )

    produto: Mapped["Produto"] = relationship(back_populates="estoque")


class Solicitacao(Base):
    """Registro de ação de escrita (intake) — não muta estado real (princípio 4)."""

    __tablename__ = "solicitacoes"

    id: Mapped[int] = mapped_column(primary_key=True)
    cliente_id: Mapped[int] = mapped_column(ForeignKey("clientes.id"), index=True)
    tipo: Mapped[TipoSolicitacao] = mapped_column(Enum(TipoSolicitacao, native_enum=False))
    # nullable: usado em cancelamento. Contrato Fase 5: validar que pertence ao cliente_id.
    pedido_id: Mapped[int | None] = mapped_column(ForeignKey("pedidos.id"), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON().with_variant(JSONB, "postgresql"))
    status: Mapped[StatusSolicitacao] = mapped_column(
        Enum(StatusSolicitacao, native_enum=False),
        default=StatusSolicitacao.pendente,
    )
    criado_em: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    cliente: Mapped["Cliente"] = relationship(back_populates="solicitacoes")
