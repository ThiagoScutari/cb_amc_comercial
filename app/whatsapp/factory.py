"""Montagem dos clients REAIS a partir das settings (.env) — só roda no host.

TODAS as keys vêm de `Settings` (.env) — NUNCA hardcoded (§15 nº7). Imports dos
SDKs externos (anthropic/openai/elevenlabs) são PREGUIÇOSOS (dentro da função) para
que importar este módulo não exija os pacotes instalados — os testes injetam fakes
no `Dispatcher` e nunca chamam esta factory.
"""

from __future__ import annotations

import httpx

from app.agent.orchestrator import HistoricoMemoria, Orquestrador
from app.config import Settings, get_settings
from app.data.db import criar_engine, criar_sessionmaker
from app.voice.stt import Transcritor
from app.voice.tts import Sintetizador
from app.whatsapp.client import WhatsAppCloudClient
from app.whatsapp.router import Dispatcher


def criar_dispatcher(settings: Settings | None = None) -> Dispatcher:
    s = settings or get_settings()

    # SDKs externos: import preguiçoso (host tem os pacotes; dev/CI não precisa).
    from anthropic import AsyncAnthropic
    from elevenlabs.client import AsyncElevenLabs
    from openai import AsyncOpenAI

    # WhatsApp Cloud API (Meta). # TODO: aguardando token permanente da Meta —
    # enquanto o .env tiver o placeholder, as chamadas voltam 401 e degradam (log + False).
    client = WhatsAppCloudClient(
        httpx.AsyncClient(timeout=30.0),
        access_token=s.whatsapp_access_token,
        phone_number_id=s.whatsapp_phone_number_id,
        api_version=s.whatsapp_api_version,
    )
    orquestrador = Orquestrador(
        AsyncAnthropic(api_key=s.anthropic_api_key), HistoricoMemoria(), s.agent_model
    )
    transcritor = Transcritor(AsyncOpenAI(api_key=s.openai_api_key))
    sintetizador = Sintetizador(
        AsyncElevenLabs(api_key=s.elevenlabs_api_key),
        voice_id=s.elevenlabs_voice_id,
        modelo=s.elevenlabs_model,
        output_format=s.elevenlabs_output_format,
    )
    sessionmaker = criar_sessionmaker(criar_engine())
    return Dispatcher(
        client=client,
        orquestrador=orquestrador,
        transcritor=transcritor,
        sintetizador=sintetizador,
        sessionmaker=sessionmaker,
    )
