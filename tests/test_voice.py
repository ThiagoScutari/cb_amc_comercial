"""Testes de voz (STT Whisper + TTS ElevenLabs) — SEM rede e SEM API key.

Fakes injetados espelham só o que cada serviço usa. O CI nunca chama OpenAI nem
ElevenLabs.
"""

from types import SimpleNamespace

import httpx
import pytest
from app.voice.stt import Transcritor
from app.voice.tts import Sintetizador
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


# ---------------------------------------------------------------------------
# TTS (ElevenLabs) — Fase 7. FakeElevenLabs espelha client.text_to_speech.convert,
# que devolve um ITERADOR ASSÍNCRONO de bytes (o HTTP real acontece na iteração —
# por isso o fake levanta o erro lá, fielmente).
# ---------------------------------------------------------------------------
class _FakeTextToSpeech:
    def __init__(self, capturas, chunks, erro):
        self.capturas = capturas
        self._chunks = chunks
        self._erro = erro

    def convert(self, **kwargs):
        self.capturas.append(kwargs)

        async def _stream():
            if self._erro is not None:  # erro/timeout/cota: surge ao iterar o stream
                raise self._erro
            for c in self._chunks:
                yield c

        return _stream()


class FakeElevenLabs:
    """Espelha só o que o Sintetizador usa: client.text_to_speech.convert -> async iter de bytes."""

    def __init__(self, chunks=(b"audio-",), erro=None):
        self.capturas: list[dict] = []
        self.text_to_speech = _FakeTextToSpeech(self.capturas, chunks, erro)


async def test_sintetiza_texto_para_audio_bytes():
    fake = FakeElevenLabs(chunks=[b"ola-", b"mundo"])
    audio = await Sintetizador(fake, voice_id="vid").sintetizar("oi, tudo bem?")
    assert audio == b"ola-mundo"  # junta os chunks do stream


async def test_texto_vazio_ou_so_espaco_retorna_none_sem_chamar_api():
    fake = FakeElevenLabs(chunks=[b"x"])
    assert await Sintetizador(fake, voice_id="vid").sintetizar("") is None
    assert await Sintetizador(fake, voice_id="vid").sintetizar("   ") is None
    assert fake.capturas == []  # nem tocou a API


async def test_audio_vazio_do_provedor_retorna_none():
    fake = FakeElevenLabs(chunks=[])  # stream sem bytes
    assert await Sintetizador(fake, voice_id="vid").sintetizar("texto") is None


@pytest.mark.parametrize(
    "erro",
    [
        RuntimeError("erro genérico do provedor"),
        TimeoutError("timeout"),
        ConnectionError("conexão caiu"),
        ValueError("cota/créditos esgotados (401/429)"),
    ],
)
async def test_qualquer_falha_degrada_para_none_sem_excecao(erro):
    # CONTRATO: a voz é aditiva — NENHUM modo de falha pode deixar o bot mudo (§15).
    # O texto sempre sai; aqui só garantimos que sintetizar() devolve None calado.
    fake = FakeElevenLabs(erro=erro)
    assert await Sintetizador(fake, voice_id="vid").sintetizar("texto") is None


async def test_passa_voice_id_modelo_e_formato_corretos():
    fake = FakeElevenLabs()
    await Sintetizador(
        fake, voice_id="VOZ123", modelo="eleven_multilingual_v2", output_format="mp3_22050_32"
    ).sintetizar("oi")
    kw = fake.capturas[0]
    assert kw["voice_id"] == "VOZ123"
    assert kw["model_id"] == "eleven_multilingual_v2"
    assert kw["output_format"] == "mp3_22050_32"
    assert kw["text"] == "oi"


def test_defaults_flash_v25_e_mp3():
    s = Sintetizador(object(), voice_id="v")  # configurável via .env; defaults p/ demo
    assert s.modelo == "eleven_flash_v2_5"
    assert s.output_format == "mp3_44100_128"
