"""Identificação telefone -> cliente_id (auth da sessão), com política fail-closed.

Chamada ANTES do agente (dispatcher, Fase 8). Resultado é uma união discriminada:
`SessaoAutenticada` (tem `cliente_id`) ou `SessaoNegada` (NÃO tem). Como `Ferramentas`
exige `cliente_id: int` e a única fonte é `SessaoAutenticada.cliente_id` (via
`cliente_id_de`), é estruturalmente impossível acessar dados no caminho negado.

Auth *stateless*: o telefone é re-resolvido a cada mensagem (sem token de sessão).
Na dúvida, NEGA (§7.2): desconhecido, inativo, ou número ambíguo -> sem dado + escala.
`escalar` é só um SINAL; o handler de escalonamento é a Fase 5 (ops/escalation.py).

Extensível (§7.1): para subir o nível (ex.: confirmação por CNPJ/código), basta
acrescentar verificações antes de devolver `SessaoAutenticada`.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

from sqlalchemy.exc import MultipleResultsFound

from app.data.repository import DadosRepository

_MSG_DESCONHECIDO = (
    "Oi! Não consegui te identificar pelo seu número por aqui. "
    "Já estou chamando uma pessoa do nosso time pra te ajudar, tá bom?"
)
_MSG_INATIVO = (
    "Encontrei seu cadastro, mas ele está inativo no momento. "
    "Vou te encaminhar pro nosso time comercial pra regularizar, tudo bem?"
)
_MSG_AMBIGUO = (
    "Encontrei mais de um cadastro com esse número. "
    "Vou te passar pra uma pessoa do time pra confirmar quem é, tá?"
)


class MotivoNegacao(enum.StrEnum):
    numero_desconhecido = "numero_desconhecido"
    cliente_inativo = "cliente_inativo"
    cadastro_ambiguo = "cadastro_ambiguo"


@dataclass(frozen=True)
class SessaoAutenticada:
    cliente_id: int  # ÚNICA fonte de cliente_id no sistema
    nome: str  # nome_fantasia, p/ saudação do agente (não-sensível)


@dataclass(frozen=True)
class SessaoNegada:
    motivo: MotivoNegacao
    mensagem: str  # texto falável ao usuário (sem markdown)
    escalar: bool = True  # SINAL p/ Fase 5/8 — não executa o handoff aqui


Sessao = SessaoAutenticada | SessaoNegada


def resolver_sessao(telefone: str | None, repo: DadosRepository) -> Sessao:
    """Resolve o telefone para uma sessão. Na dúvida, NEGA (fail-closed)."""
    try:
        cliente = repo.cliente_por_telefone(telefone or "")
    except MultipleResultsFound:
        # >1 cliente p/ o número (sem unique no ERP futuro, §6.4): negar, não
        # autenticar o errado nem vazar stack trace.
        return SessaoNegada(MotivoNegacao.cadastro_ambiguo, _MSG_AMBIGUO)
    if cliente is None:
        return SessaoNegada(MotivoNegacao.numero_desconhecido, _MSG_DESCONHECIDO)
    if not cliente.ativo:
        return SessaoNegada(MotivoNegacao.cliente_inativo, _MSG_INATIVO)
    return SessaoAutenticada(cliente_id=cliente.id, nome=cliente.nome_fantasia)


def cliente_id_de(sessao: Sessao) -> int | None:
    """Único ponto que extrai cliente_id. Negada -> None (chokepoint fail-closed)."""
    return sessao.cliente_id if isinstance(sessao, SessaoAutenticada) else None
