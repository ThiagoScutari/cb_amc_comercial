"""Testes do STT (Whisper) — SEM rede e SEM API key.

FakeOpenAI injetado espelha o mínimo de client.audio.transcriptions.create.
"""

from types import SimpleNamespace

import httpx
from app.voice.stt import Transcritor
from openai import APIConnectionError


class _FakeTranscriptions:
    def __init__(self, capturas, texto, erro):
        self.capturas = capturas
        self._texto = texto
        self._erro = erro

    async def create(self, **kwargs):
        self.capturas.append(kwargs)
        if self._erro is not None:
            raise self._erro
        return SimpleNamespace(text=self._texto)


class FakeOpenAI:
    """Espelha só o que o Transcritor usa: client.audio.transcriptions.create."""

    def __init__(self, texto="", erro=None):
        self.capturas: list[dict] = []
        self.audio = SimpleNamespace(transcriptions=_FakeTranscriptions(self.capturas, texto, erro))


async def test_transcreve_audio_para_texto():
    fake = FakeOpenAI(texto="cadê meu pedido 4471")
    texto = await Transcritor(fake).transcrever(b"...ogg-bytes...")
    assert texto == "cadê meu pedido 4471"


async def test_audio_vazio_retorna_none():
    fake = FakeOpenAI(texto="qualquer")
    assert await Transcritor(fake).transcrever(b"") is None
    assert fake.capturas == []  # nem chamou a API


async def test_transcricao_vazia_ou_so_espaco_retorna_none():
    fake = FakeOpenAI(texto="   ")
    assert await Transcritor(fake).transcrever(b"abc") is None


async def test_erro_da_api_degrada_para_none():
    erro = APIConnectionError(
        request=httpx.Request("POST", "https://api.openai.com/v1/audio/transcriptions")
    )
    fake = FakeOpenAI(erro=erro)
    assert await Transcritor(fake).transcrever(b"abc") is None


async def test_forca_idioma_pt_e_modelo_whisper():
    fake = FakeOpenAI(texto="oi")
    await Transcritor(fake).transcrever(b"abc")
    kwargs = fake.capturas[0]
    assert kwargs["language"] == "pt"  # força PT-BR
    assert kwargs["model"] == "whisper-1"
