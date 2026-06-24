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

from app.data.models import (
    Cliente,
    Devolucao,
    NotaFiscal,
    Pedido,
    Solicitacao,
    StatusPedido,
    StatusTitulo,
    Titulo,
)
from app.data.repository import DadosRepository
from app.ops.escalation import registrar_escalonamento


class PedidoItemView(BaseModel):
    sku: str
    ref_produto: str  # RefId Colcci (ex.: "340103413") — como o lojista B2B identifica a peça
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
                    ref_produto=it.sku.ref_produto,
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
    ref_produto: str  # RefId Colcci — referência que o lojista usa no sistema dele
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


class SolicitacaoView(BaseModel):
    # Mínima: o modelo compõe a frase falável ("registrei, o time retorna").
    id: int
    tipo: str
    status: str
    pedido_id: int | None = None

    @classmethod
    def from_model(cls, s: Solicitacao) -> SolicitacaoView:
        return cls(id=s.id, tipo=s.tipo.value, status=s.status.value, pedido_id=s.pedido_id)


class EscalonamentoView(BaseModel):
    registrado: bool = True
    motivo: str


class ClienteView(BaseModel):
    # Exposição MÍNIMA: só dado comercial não-sensível da conta da SESSÃO. NÃO inclui
    # CNPJ, razão social, telefone nem nada interno (princípio do menor privilégio).
    condicao_pagamento: str
    cidade_uf: str

    @classmethod
    def from_model(cls, c: Cliente) -> ClienteView:
        return cls(condicao_pagamento=c.condicao_pagamento, cidade_uf=c.cidade_uf)


class NotaFiscalView(BaseModel):
    # Dados que o cliente veria no Portal. Chave de negócio (numero_nf) + chave_acesso (NF-e)
    # são legítimos; NÃO expõe id interno nem cliente_id (já isolado no repository, S13).
    numero_nf: int
    numero_pedido: int
    data_emissao: dt.date
    valor_total: Decimal
    chave_acesso: str
    status_entrega: str
    transportadora: str | None
    codigo_rastreio: str | None
    data_prevista_entrega: dt.date | None
    data_entrega: dt.date | None

    @classmethod
    def from_model(cls, nf: NotaFiscal) -> NotaFiscalView:
        return cls(
            numero_nf=nf.numero_nf,
            numero_pedido=nf.pedido_id,
            data_emissao=nf.data_emissao,
            valor_total=nf.valor_total,
            chave_acesso=nf.chave_acesso,
            status_entrega=nf.status_entrega.value,
            transportadora=nf.transportadora,
            codigo_rastreio=nf.codigo_rastreio,
            data_prevista_entrega=nf.data_prevista_entrega,
            data_entrega=nf.data_entrega,
        )


class TituloView(BaseModel):
    # numero_nf é o número de NEGÓCIO da NF amarrada (não a PK interna). linha_digitavel
    # (boleto) é legítima — o cliente precisa dela p/ pagar.
    numero_titulo: str
    numero_nf: int
    parcela: str
    valor: Decimal
    data_vencimento: dt.date
    status: str
    data_pagamento: dt.date | None
    linha_digitavel: str

    @classmethod
    def from_model(cls, t: Titulo) -> TituloView:
        return cls(
            numero_titulo=t.numero_titulo,
            numero_nf=t.nota_fiscal.numero_nf,
            parcela=t.parcela,
            valor=t.valor,
            data_vencimento=t.data_vencimento,
            status=t.status.value,
            data_pagamento=t.data_pagamento,
            linha_digitavel=t.linha_digitavel,
        )


class DevolucaoView(BaseModel):
    numero_devolucao: str
    numero_nf: int
    motivo: str
    status: str
    codigo_postagem: str | None
    prazo_postagem: dt.date | None
    valor_credito: Decimal | None
    data_credito: dt.date | None
    data_solicitacao: dt.date

    @classmethod
    def from_model(cls, d: Devolucao) -> DevolucaoView:
        return cls(
            numero_devolucao=d.numero_devolucao,
            numero_nf=d.nota_fiscal.numero_nf,
            motivo=d.motivo,
            status=d.status.value,
            codigo_postagem=d.codigo_postagem,
            prazo_postagem=d.prazo_postagem,
            valor_credito=d.valor_credito,
            data_credito=d.data_credito,
            data_solicitacao=d.data_solicitacao,
        )


class FaturamentoView(BaseModel):
    # Agregado read-only (envolve o dict de consultar_faturamento p/ uniformidade: BaseModel).
    pedidos_total: int
    pedidos_faturados: int
    pedidos_a_faturar: int
    valor_faturado: Decimal
    valor_a_faturar: Decimal


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
                ref_produto=p.ref_produto,
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

    def consultar_dados_cliente(self) -> ClienteView | NaoEncontrado:
        # cliente_id da SESSÃO, nunca do modelo: a tool NÃO tem parâmetros (princípio 2).
        c = self.repo.dados_cliente(self.cliente_id)
        if c is None:
            return NaoEncontrado(mensagem="Não consegui localizar os dados da sua conta.")
        return ClienteView.from_model(c)

    # --- FISCAL / FINANCEIRO (S14): read-only; cliente_id da SESSÃO, nunca do modelo ---
    def consultar_nota_fiscal(self, numero_nf: int) -> NotaFiscalView | NaoEncontrado:
        nf = self.repo.consultar_nota_fiscal(self.cliente_id, numero_nf)  # injeta cliente_id
        if nf is None:
            return NaoEncontrado(mensagem="Não encontrei essa nota fiscal.")
        return NotaFiscalView.from_model(nf)

    def listar_notas_fiscais(self) -> list[NotaFiscalView]:
        return [
            NotaFiscalView.from_model(nf) for nf in self.repo.listar_notas_fiscais(self.cliente_id)
        ]

    def consultar_titulo(self, numero_titulo: str) -> TituloView | NaoEncontrado:
        t = self.repo.consultar_titulo(self.cliente_id, numero_titulo)
        if t is None:
            return NaoEncontrado(mensagem="Não encontrei esse título.")
        return TituloView.from_model(t)

    def listar_titulos(self, filtro_status: str | None = None) -> list[TituloView]:
        if filtro_status is not None:
            status = _status_titulo_ou_invalido(filtro_status)
            if status is None:
                return []  # status inválido -> lista vazia (não erro, não "todos")
            titulos = self.repo.listar_titulos(self.cliente_id, status)
        else:
            titulos = self.repo.listar_titulos(self.cliente_id)
        return [TituloView.from_model(t) for t in titulos]

    def consultar_devolucao(self, numero_devolucao: str) -> DevolucaoView | NaoEncontrado:
        d = self.repo.consultar_devolucao(self.cliente_id, numero_devolucao)
        if d is None:
            return NaoEncontrado(mensagem="Não encontrei essa devolução.")
        return DevolucaoView.from_model(d)

    def listar_devolucoes(self) -> list[DevolucaoView]:
        return [DevolucaoView.from_model(d) for d in self.repo.listar_devolucoes(self.cliente_id)]

    def consultar_faturamento(self) -> FaturamentoView:
        # cliente_id da SESSÃO: a tool NÃO tem parâmetros. Envolve o dict do repo numa View.
        return FaturamentoView(**self.repo.consultar_faturamento(self.cliente_id))

    # --- INTAKE: registra + avisa (NÃO executa, NÃO muta) ---
    def solicitar_cancelamento(
        self, numero_pedido: int, motivo: str | None = None
    ) -> SolicitacaoView | NaoEncontrado:
        # cliente_id da sessão, nunca do modelo. Anti-IDOR de escrita no repository.
        sol = self.repo.registrar_cancelamento(self.cliente_id, numero_pedido, motivo)
        if sol is None:
            return NaoEncontrado(mensagem="Não encontrei esse pedido na sua conta pra cancelar.")
        return SolicitacaoView.from_model(sol)

    def solicitar_compra(self, itens: list[dict]) -> SolicitacaoView:
        return SolicitacaoView.from_model(self.repo.registrar_compra(self.cliente_id, itens))

    def escalar_para_humano(self, motivo: str) -> EscalonamentoView:
        esc = registrar_escalonamento(motivo, cliente_id=self.cliente_id)
        return EscalonamentoView(registrado=True, motivo=esc.motivo)


def _status_ou_none(valor: str | None) -> StatusPedido | None:
    if not valor:
        return None
    try:
        return StatusPedido(valor)
    except ValueError:
        return None


def _status_titulo_ou_invalido(valor: str) -> StatusTitulo | None:
    """Converte o filtro de status do título -> StatusTitulo. None se inválido.

    Aceita o NOME do membro (`em_aberto`/`pago`/`vencido`, como o schema declara) e também
    o valor exibido (`"Em aberto"`/`"Pago"`/`"Vencido"`). Inválido -> None (a tool devolve
    lista vazia, nunca erro).
    """
    try:
        return StatusTitulo[valor]  # por nome (o que TOOL_DEFS expõe ao modelo)
    except KeyError:
        pass
    try:
        return StatusTitulo(valor)  # tolera o valor exibido
    except ValueError:
        return None


# Schemas dos tools para a Claude API (Fase 4). NENHUM traz `cliente_id`: o modelo
# não o vê; o código o injeta a partir de `Ferramentas.cliente_id` (princípio 2).
TOOL_DEFS: list[dict] = [
    {
        "name": "consultar_pedido",
        "description": (
            "Consulta um pedido do cliente pelo número. Use quando a pessoa citar um "
            "número de pedido. Retorna status, prazo de entrega, itens e se está faturado."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "numero_pedido": {
                    "type": "integer",
                    "description": "Número do pedido citado pelo cliente.",
                }
            },
            "required": ["numero_pedido"],
            "additionalProperties": False,
        },
    },
    {
        "name": "listar_pedidos",
        "description": (
            "Lista os pedidos do cliente. Use para 'meus pedidos'. Pode filtrar por status."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "filtro_status": {
                    "type": "string",
                    "description": "Status para filtrar (ex.: Entregue, Confirmado, Faturado).",
                }
            },
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "name": "buscar_produto",
        "description": "Busca produtos do catálogo por texto livre (ex.: 'camiseta branca M').",
        "input_schema": {
            "type": "object",
            "properties": {
                "texto_busca": {"type": "string", "description": "Descrição do produto buscado."}
            },
            "required": ["texto_busca"],
            "additionalProperties": False,
        },
    },
    {
        "name": "consultar_disponibilidade",
        "description": (
            "Consulta a disponibilidade (saldo livre) de um produto, por sku ou por "
            "produto/cor/tamanho. Use para 'tem pra comprar?'. Responde só o saldo."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "produto": {"type": "string"},
                "tamanho": {"type": "string"},
                "cor": {"type": "string"},
                "sku": {"type": "string"},
            },
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "name": "solicitar_cancelamento",
        "description": (
            "Registra uma solicitação de cancelamento de pedido. NÃO cancela nada — só "
            "registra para o time processar. Use SOMENTE depois de ler os dados do pedido "
            "de volta e o cliente confirmar."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "numero_pedido": {"type": "integer"},
                "motivo": {"type": "string"},
            },
            "required": ["numero_pedido"],
            "additionalProperties": False,
        },
    },
    {
        "name": "solicitar_compra",
        "description": (
            "Registra uma solicitação de compra/novo pedido (atacado B2B). NÃO cria pedido "
            "— só registra para o time processar. Use SOMENTE depois de montar o rascunho, "
            "ler de volta e o cliente confirmar."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "itens": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "sku": {"type": "string"},
                            "quantidade": {"type": "integer"},
                        },
                        "required": ["sku", "quantidade"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["itens"],
            "additionalProperties": False,
        },
    },
    {
        "name": "consultar_dados_cliente",
        "description": (
            "Informa dados comerciais da conta de quem está falando: condição de "
            "pagamento e cidade. Use para 'qual minha condição de pagamento?'. NÃO recebe "
            "parâmetros — é sempre a conta do próprio cliente da conversa."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "name": "escalar_para_humano",
        "description": (
            "Encaminha o atendimento para uma pessoa do time. Use quando o cliente pedir "
            "uma pessoa, ou o assunto estiver fora do escopo (pedidos, prazos, "
            "disponibilidade, compra). Registra o pedido; o time retorna."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"motivo": {"type": "string"}},
            "required": ["motivo"],
            "additionalProperties": False,
        },
    },
    {
        "name": "consultar_nota_fiscal",
        "description": (
            "Consulta uma nota fiscal do cliente pelo número. Use quando pedirem cópia/2ª "
            "via de NF ou a posição de entrega de uma nota (transportadora, rastreio, prazo)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "numero_nf": {"type": "integer", "description": "Número da nota fiscal."}
            },
            "required": ["numero_nf"],
            "additionalProperties": False,
        },
    },
    {
        "name": "listar_notas_fiscais",
        "description": "Lista as notas fiscais do cliente.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "name": "consultar_titulo",
        "description": (
            "Consulta um título financeiro (duplicata/boleto) do cliente pelo número. Use "
            "para cópia/2ª via de título ou situação de uma parcela."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"numero_titulo": {"type": "string", "description": "Número do título."}},
            "required": ["numero_titulo"],
            "additionalProperties": False,
        },
    },
    {
        "name": "listar_titulos",
        "description": (
            "Lista os títulos financeiros do cliente (financeiro). Pode filtrar por situação."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "filtro_status": {
                    "type": "string",
                    "enum": ["em_aberto", "pago", "vencido"],
                    "description": "Situação para filtrar os títulos.",
                }
            },
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "name": "consultar_devolucao",
        "description": (
            "Consulta uma devolução do cliente pelo número. Use para posição da devolução, "
            "prazo/código de postagem e crédito gerado."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "numero_devolucao": {"type": "string", "description": "Número da devolução."}
            },
            "required": ["numero_devolucao"],
            "additionalProperties": False,
        },
    },
    {
        "name": "listar_devolucoes",
        "description": "Lista as devoluções do cliente, com situação e crédito.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "name": "consultar_faturamento",
        "description": (
            "Resumo do faturamento do cliente: quantos pedidos já viraram nota fiscal e "
            "quanto está faturado vs a faturar. Não recebe parâmetros."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
    },
]

NOMES_TOOLS: frozenset[str] = frozenset(d["name"] for d in TOOL_DEFS)
PARAMS_TOOLS: dict[str, frozenset[str]] = {
    d["name"]: frozenset(d["input_schema"]["properties"]) for d in TOOL_DEFS
}
