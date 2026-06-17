"""Cliente da Evolution API (WhatsApp): envio de texto/áudio e fetch de mídia.

Auth por header `apikey` (key da instância, lida de settings — NUNCA hardcoded).
O `httpx.AsyncClient` é INJETADO (testes usam um fake; CI sem rede). Todo método
degrada em erro (log + False/None) — NADA aqui pode derrubar o app nem a task do
dispatcher (§15): uma falha de rede da Evolution faz a resposta se perder, não o
processo cair.

Áudio: mando MP3 em base64 (Fase 7) p/ `sendWhatsAppAudio`; a Evolution transcodifica
para a nota de voz (ptt opus) — por isso não há ffmpeg no nosso Dockerfile. O fetch
do áudio recebido (`getBase64FromMediaMessage`) devolve base64 -> bytes, que é o que
o `Transcritor` da Fase 6 espera.
"""

from __future__ import annotations

import base64
import logging
from typing import Any, Protocol

import httpx

logger = logging.getLogger("cb_amc_comercial.whatsapp")


class EnvioWhatsApp(Protocol):
    """Porta que o dispatcher usa — permite injetar um fake nos testes."""

    async def enviar_texto(self, telefone: str, texto: str) -> bool: ...
    async def enviar_audio(self, telefone: str, audio: bytes) -> bool: ...
    async def buscar_audio(self, mensagem: dict) -> bytes | None: ...


class EvolutionClient:
    def __init__(
        self, http: httpx.AsyncClient, *, base_url: str, apikey: str, instancia: str
    ) -> None:
        self.http = http
        self.base_url = base_url.rstrip("/")
        self.apikey = apikey
        self.instancia = instancia

    @property
    def _headers(self) -> dict[str, str]:
        return {"apikey": self.apikey, "Content-Type": "application/json"}

    async def _post(self, caminho: str, payload: dict[str, Any]) -> dict | None:
        try:
            resp = await self.http.post(
                f"{self.base_url}{caminho}", json=payload, headers=self._headers
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:  # noqa: BLE001 - Evolution fora/erro: degrada, não derruba (§15)
            logger.warning("evolution POST %s falhou: %s", caminho, str(exc)[:120])
            return None

    async def enviar_texto(self, telefone: str, texto: str) -> bool:
        r = await self._post(
            f"/message/sendText/{self.instancia}", {"number": telefone, "text": texto}
        )
        return r is not None

    async def enviar_audio(self, telefone: str, audio: bytes) -> bool:
        b64 = base64.b64encode(audio).decode("ascii")
        r = await self._post(
            f"/message/sendWhatsAppAudio/{self.instancia}", {"number": telefone, "audio": b64}
        )
        return r is not None

    async def buscar_audio(self, mensagem: dict) -> bytes | None:
        """Recupera o áudio recebido (base64) e devolve bytes. None se falhar."""
        r = await self._post(
            f"/chat/getBase64FromMediaMessage/{self.instancia}", {"message": mensagem}
        )
        if not r:
            return None
        b64 = r.get("base64") or (r.get("media") or {}).get("base64")
        if not b64:
            return None
        try:
            return base64.b64decode(b64)
        except Exception:  # noqa: BLE001 - base64 corrompido -> degrada p/ None
            return None

    async def aclose(self) -> None:
        await self.http.aclose()
