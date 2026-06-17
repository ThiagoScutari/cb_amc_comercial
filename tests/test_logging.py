"""Testes da config central de logging."""

import logging

from app.logging_config import configurar_logging


def test_configurar_logging_define_nivel_explicito():
    configurar_logging("WARNING")
    assert logging.getLogger().level == logging.WARNING


def test_configurar_logging_le_das_settings_por_default():
    configurar_logging()  # default = Settings.log_level (INFO)
    assert logging.getLogger().level == logging.INFO
