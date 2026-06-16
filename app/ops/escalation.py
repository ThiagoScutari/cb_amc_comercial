"""Fallback para humano (§11.1). MVP = log-only: não há atendente plugado ainda.

Handler único que TODOS os gatilhos chamam — sinal da auth (Fase 3:
desconhecido/inativo/ambíguo), pedido explícito do cliente, fora de escopo, ou
falha de ferramenta/API. Retenção mínima (§12): loga só motivo + cliente_id + um
detalhe CURTO e truncado — nunca o payload/conteúdo da conversa.

Quando existir uma fila humana real, trocar o corpo por uma persistência/notificação
sem mudar a assinatura (Fase 8/deploy).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger("cb_amc_comercial.escalonamento")

_MAX_MOTIVO = 60
_MAX_DETALHE = 120


@dataclass(frozen=True)
class Escalonamento:
    motivo: str
    cliente_id: int | None
    detalhe: str


def registrar_escalonamento(
    motivo: object, cliente_id: int | None = None, detalhe: str = ""
) -> Escalonamento:
    motivo_curto = str(motivo)[:_MAX_MOTIVO]
    detalhe_curto = (detalhe or "")[:_MAX_DETALHE]
    logger.warning(
        "escalonamento motivo=%s cliente_id=%s detalhe=%s",
        motivo_curto,
        cliente_id,
        detalhe_curto,
    )
    return Escalonamento(motivo=motivo_curto, cliente_id=cliente_id, detalhe=detalhe_curto)
