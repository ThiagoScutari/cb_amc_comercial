"""Configuração central de logging — formato key=value (grep-able).

Chamada no startup (main.lifespan). Lê o nível de `Settings.log_level`. NÃO loga
conteúdo de conversa (§12): quem emite (ex.: escalation.py) já trunca e só registra
motivo/cliente_id/detalhe curto. Retenção mínima é responsabilidade de cada emissor.
"""

from __future__ import annotations

import logging

from app.config import get_settings

_FORMATO = "%(asctime)s level=%(levelname)s logger=%(name)s %(message)s"


def configurar_logging(nivel: str | None = None) -> None:
    nivel = (nivel or get_settings().log_level).upper()
    logging.basicConfig(level=nivel, format=_FORMATO, force=True)
