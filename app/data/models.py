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


class StatusPedido(enum.StrEnum):
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


class TipoSolicitacao(enum.StrEnum):
    cancelamento = "cancelamento"
    compra = "compra"


class StatusSolicitacao(enum.StrEnum):
    pendente = "pendente"


class StatusEntrega(enum.StrEnum):
    """Posição de entrega de uma NF-e (rastreio sintético, read-only) — S11."""

    emitida = "Emitida"
    coletada = "Coletada"
    em_transito = "Em trânsito"
    entregue = "Entregue"


class StatusTitulo(enum.StrEnum):
    """Situação de um título financeiro / duplicata (read-only) — S11."""

    em_aberto = "Em aberto"
    pago = "Pago"
    vencido = "Vencido"


class StatusDevolucao(enum.StrEnum):
    """Ciclo de uma devolução até a geração de crédito (read-only) — S11."""

    solicitada = "Solicitada"
    em_analise = "Em análise"
    aguardando_postagem = "Aguardando postagem"
    prazo_postagem_expirado = "Prazo de postagem expirado"
    em_transito = "Em trânsito"
    recebida = "Recebida"
    credito_gerado = "Crédito gerado"


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


def parse_ref_produto(ref: str | None) -> tuple[str | None, str | None, str | None]:
    """Decodifica o RefId Colcci `TTT.MM.NNNNN` ancorando pela DIREITA (v1.8).

    O site remove os pontos e corta zeros à esquerda, então o ref tem tamanho
    variável (tipo de 1–3 díg). Regra fixa (ancorada à direita):
        ordem     = ref[-5:]
        marca_cod = ref[-7:-5]
        tipo_cod  = ref[:-7] re-padded a 3 díg (zfill)
    Ex.: "80104766" -> ("008", "01", "04766"); "340103413" -> ("034", "01", "03413").

    Faixa válida = 7..10 díg (teto absoluto 3+2+5). Fora dela ou não-numérico ->
    (None, None, None), sem exceção (nunca inventa tipo de 4+ díg).
    """
    if not ref or not ref.isdigit() or not (7 <= len(ref) <= 10):
        return None, None, None
    return ref[:-7].zfill(3), ref[-7:-5], ref[-5:]


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
    # S11 — entidades fiscais/financeiras (carregam cliente_id; isolamento na fase futura):
    notas_fiscais: Mapped[list["NotaFiscal"]] = relationship(back_populates="cliente")
    titulos: Mapped[list["Titulo"]] = relationship(back_populates="cliente")
    devolucoes: Mapped[list["Devolucao"]] = relationship(back_populates="cliente")


class Produto(Base):
    """1 linha = 1 SKU (produto × tamanho × cor). Catálogo Colcci — global."""

    __tablename__ = "produtos"

    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(String(20), unique=True, index=True)  # "360118439-M"
    # ref Colcci: 9 díg. (tops) OU 8 díg. (bottoms). Não é mais str(9) — ver §5.2 (S01b).
    ref_produto: Mapped[str] = mapped_column(String(12), index=True)
    # Derivados do ref por âncora-direita (v1.8); null só p/ ref malformado (<7 díg).
    # tipo_cod (3 díg) codifica peça+gênero (ex.: 001=calça masc, 002=calça fem).
    tipo_cod: Mapped[str | None] = mapped_column(String(3), nullable=True)
    marca_cod: Mapped[str | None] = mapped_column(String(2), nullable=True)
    ordem: Mapped[str | None] = mapped_column(String(5), nullable=True)
    # Confiável (vem da extração/listagem); usado na busca ("camiseta masculina").
    genero: Mapped[str] = mapped_column(String(10))  # "Feminino" | "Masculino"
    categoria_txt: Mapped[str | None] = mapped_column(String(60), nullable=True)
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


class NotaFiscal(Base):
    """NF-e sintética: elo pedido ↔ entrega ↔ financeiro. Read-only (S11).

    Carrega `cliente_id` como âncora anti-IDOR (princípio 2), igual a `Pedido` —
    o filtro por cliente_id no repository é da fase futura (S12). `pedido_id` é a
    via para validar posse de NFs amarradas a pedido (anti-IDOR de leitura, S12).
    """

    __tablename__ = "notas_fiscais"

    # PK inteira INSERÍVEL (igual a Pedido): o seed atribui o número.
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    numero_nf: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    cliente_id: Mapped[int] = mapped_column(ForeignKey("clientes.id"), index=True)
    pedido_id: Mapped[int] = mapped_column(ForeignKey("pedidos.id"), index=True)
    data_emissao: Mapped[dt.date] = mapped_column(Date)
    chave_acesso: Mapped[str] = mapped_column(String(44))  # 44 díg. da NF-e (sintética)
    valor_total: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    # create_constraint=True: emite o CHECK de fato (o default do SQLAlchemy 2.0 é False).
    status_entrega: Mapped[StatusEntrega] = mapped_column(
        Enum(StatusEntrega, native_enum=False, create_constraint=True)
    )
    transportadora: Mapped[str | None] = mapped_column(String(60), nullable=True)
    codigo_rastreio: Mapped[str | None] = mapped_column(String(40), nullable=True)
    data_prevista_entrega: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    data_entrega: Mapped[dt.date | None] = mapped_column(Date, nullable=True)

    cliente: Mapped["Cliente"] = relationship(back_populates="notas_fiscais")
    pedido: Mapped["Pedido"] = relationship()  # via única; Pedido não tem inverso (S11)
    titulos: Mapped[list["Titulo"]] = relationship(back_populates="nota_fiscal")
    devolucoes: Mapped[list["Devolucao"]] = relationship(back_populates="nota_fiscal")


class Titulo(Base):
    """Título financeiro (duplicata) ligado a uma NF. Carrega cliente_id (S11)."""

    __tablename__ = "titulos"

    id: Mapped[int] = mapped_column(primary_key=True)
    numero_titulo: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    cliente_id: Mapped[int] = mapped_column(ForeignKey("clientes.id"), index=True)
    nota_fiscal_id: Mapped[int] = mapped_column(ForeignKey("notas_fiscais.id"), index=True)
    parcela: Mapped[str] = mapped_column(String(8))  # ex. "1/3"
    valor: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    data_vencimento: Mapped[dt.date] = mapped_column(Date)
    status: Mapped[StatusTitulo] = mapped_column(
        Enum(StatusTitulo, native_enum=False, create_constraint=True)
    )
    data_pagamento: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    linha_digitavel: Mapped[str] = mapped_column(String(60))  # sintética

    cliente: Mapped["Cliente"] = relationship(back_populates="titulos")
    nota_fiscal: Mapped["NotaFiscal"] = relationship(back_populates="titulos")


class Devolucao(Base):
    """Devolução até a geração de crédito (read-only). Carrega cliente_id (S11).

    O crédito (`valor_credito`/`data_credito`) é DADO PRÉ-SEMEADO no mock, não uma
    ação em runtime — o bot continua somente-leitura (princípio 4).
    """

    __tablename__ = "devolucoes"

    id: Mapped[int] = mapped_column(primary_key=True)
    numero_devolucao: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    cliente_id: Mapped[int] = mapped_column(ForeignKey("clientes.id"), index=True)
    nota_fiscal_id: Mapped[int] = mapped_column(ForeignKey("notas_fiscais.id"), index=True)
    motivo: Mapped[str] = mapped_column(String(120))
    status: Mapped[StatusDevolucao] = mapped_column(
        Enum(StatusDevolucao, native_enum=False, create_constraint=True)
    )
    codigo_postagem: Mapped[str | None] = mapped_column(String(40), nullable=True)
    prazo_postagem: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    valor_credito: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    data_credito: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    data_solicitacao: Mapped[dt.date] = mapped_column(Date)

    __table_args__ = (
        CheckConstraint(
            "valor_credito IS NULL OR valor_credito >= 0",
            name="ck_devolucao_credito_nao_negativo",
        ),
    )

    cliente: Mapped["Cliente"] = relationship(back_populates="devolucoes")
    nota_fiscal: Mapped["NotaFiscal"] = relationship(back_populates="devolucoes")
