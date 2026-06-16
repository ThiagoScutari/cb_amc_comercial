"""STT: áudio (.ogg/opus do WhatsApp) -> texto PT-BR via Whisper (§8.1).

Porta de ENTRADA: a voz só vira texto; o texto entra no MESMO orchestrator.responder()
(sem caminho paralelo de lógica). O `Transcritor` recebe `bytes` — é agnóstico à
Evolution; quem busca/decodifica a mídia é a Fase 8 (whatsapp/client.py).

Cliente `AsyncOpenAI` INJETADO (testes usam um fake -> CI sem rede e sem API key).
Degradação graciosa: vazio/ininteligível/erro de API -> None (o dispatcher pede pra
repetir). Erro de STT plausível (número trocado) é pego depois pelo read-back do
system_prompt (Fase 5).
"""

from __future__ import annotations

from openai import AsyncOpenAI, OpenAIError

_MODELO = "whisper-1"


class Transcritor:
    def __init__(self, client: AsyncOpenAI, modelo: str = _MODELO) -> None:
        self.client = client
        self.modelo = modelo

    async def transcrever(
        self, audio: bytes, *, nome: str = "audio.ogg", idioma: str = "pt"
    ) -> str | None:
        if not audio:
            return None
        try:
            resp = await self.client.audio.transcriptions.create(
                model=self.modelo,
                file=(nome, audio),
                language=idioma,  # força PT-BR (menos erro de detecção)
            )
        except OpenAIError:  # timeout/rate-limit/conexão/erro -> degrada
            return None
        texto = (getattr(resp, "text", "") or "").strip()
        return texto or None  # vazio/só espaço -> None
