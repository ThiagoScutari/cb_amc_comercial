"""Testes do handler de escalonamento (log-only no MVP; retenção mínima §12)."""

import logging

from app.auth.session import MotivoNegacao
from app.ops.escalation import Escalonamento, registrar_escalonamento


def test_registrar_escalonamento_loga_motivo_e_cliente(caplog):
    with caplog.at_level(logging.WARNING):
        esc = registrar_escalonamento(
            MotivoNegacao.numero_desconhecido, cliente_id=7, detalhe="num novo"
        )
    assert isinstance(esc, Escalonamento)
    assert esc.motivo == "numero_desconhecido"
    assert esc.cliente_id == 7
    texto = " ".join(r.getMessage() for r in caplog.records)
    assert "numero_desconhecido" in texto
    assert "7" in texto


def test_escalonamento_nao_ecoa_payload_grande(caplog):
    # cuidado de retenção (§12), não brecha: detalhe é truncado, não ecoa payload inteiro.
    segredo = "SENHA-SUPER-SECRETA-" + "x" * 5000
    with caplog.at_level(logging.WARNING):
        esc = registrar_escalonamento("pedido_humano", cliente_id=1, detalhe=segredo)
    assert len(esc.detalhe) <= 120
    texto = " ".join(r.getMessage() for r in caplog.records)
    assert len(texto) < 500
    assert segredo not in texto
