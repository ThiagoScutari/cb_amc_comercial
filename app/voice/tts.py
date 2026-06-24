"""TTS: texto (resposta JÁ pronta do agente) -> áudio OGG/OPUS via ElevenLabs (§8.3).

Porta de SAÍDA (espelho do STT da Fase 6): o `Sintetizador` recebe o MESMO texto
que `orchestrator.responder()` produziu e o transforma em voz. NÃO há geração de
conteúdo paralela — o que o cliente OUVE é byte-a-byte o que ele LERIA.

CONTRATO DE FRONTEIRA (testado na Fase 8, onde o envio acontece):
    áudio None  ⇒  o texto JÁ foi (ou será) entregue ao cliente.
A voz é ADITIVA e best-effort. Falha de TTS NUNCA bloqueia a resposta escrita — o
bot nunca fica mudo. Por isso `sintetizar()` degrada para `None` em TODO modo de
falha (erro/timeout/cota/vazio) sem deixar exceção escapar.

Formato: OGG/OPUS no fio (`opus_48000_64` por default, mono). É condição NECESSÁRIA para o
WhatsApp renderizar como NOTA DE VOZ (ptt), mas NÃO suficiente: o envio também precisa marcar
`voice: true` no objeto audio (ver client.enviar_audio) — só o formato não basta. O valor
EFETIVO vem das settings (.env); o default aqui é só fallback e DEVE acompanhar o config —
um mp3 aqui, enviado como `audio/ogg` no upload, dá 400 na Graph API.

Cliente ElevenLabs (`AsyncElevenLabs`) INJETADO — agnóstico e testável com um fake
(CI sem rede e sem API key). O client real é montado por uma factory na Fase 8.
Modelo/voz/formato são configuráveis via settings (.env) p/ ajustar qualidade×latência
antes da demo (Flash v2.5 rápido vs Multilingual v2 mais natural).
"""

from __future__ import annotations

_MODELO = "eleven_flash_v2_5"  # baixa latência p/ WhatsApp ao vivo; flip via .env
_FORMATO = "opus_48000_64"  # OGG/OPUS mono = nota de voz (ptt); espelha o default do config


class Sintetizador:
    def __init__(
        self,
        client,
        *,
        voice_id: str,
        modelo: str = _MODELO,
        output_format: str = _FORMATO,
    ) -> None:
        self.client = client
        self.voice_id = voice_id
        self.modelo = modelo
        self.output_format = output_format

    async def sintetizar(self, texto: str) -> bytes | None:
        if not texto or not texto.strip():
            return None  # nada a falar -> nem chama a API
        try:
            stream = self.client.text_to_speech.convert(
                voice_id=self.voice_id,
                model_id=self.modelo,
                text=texto,
                output_format=self.output_format,
            )
            chunks = [chunk async for chunk in stream]
        except Exception:  # noqa: BLE001 - voz é aditiva: NENHUMA falha de TTS pode deixar o bot mudo (§15)
            return None
        audio = b"".join(chunks)
        return audio or None  # resposta vazia do provedor -> None (degrada p/ texto)
