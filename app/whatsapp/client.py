"""Cliente da WhatsApp Cloud API (Meta/Graph): envio de texto/áudio/documento e
fetch de mídia recebida.

Substitui o antigo `EvolutionClient` (Baileys, não-oficial), que teve a conta
restringida pela Meta. A INTERFACE PÚBLICA é a mesma (`Protocol EnvioWhatsApp`):
`enviar_texto`, `enviar_audio`, `enviar_documento`, `buscar_audio` — por isso o
`Dispatcher`/`llm_handler` não mudam.

Auth: header `Authorization: Bearer <ACCESS_TOKEN>` em TODA chamada (token lido de
settings — NUNCA hardcoded). O `httpx.AsyncClient` é INJETADO (testes usam um fake;
CI sem rede). Todo método degrada em erro (log + False/None) — NADA aqui pode derrubar
o app nem a task do dispatcher (§15): uma falha de rede da Meta faz a resposta se
perder, não o processo cair.

Mídia (áudio/documento) é em DOIS passos na Cloud API:
  1) upload multipart em `/{phone_number_id}/media` -> `media_id`;
  2) mensagem referenciando o `media_id` (`type:audio`/`type:document`).

Áudio: mando MP3 (`audio/mpeg`) como `type:audio`. A Cloud API NÃO transcodifica
(diferente da Evolution) — então toca inline como arquivo de áudio, não como nota de
voz (ptt).
# TODO(polimento): ptt real (nota de voz) exige OGG/OPUS; avaliar trocar o
# ELEVENLABS_OUTPUT_FORMAT p/ opus quando validarmos se a nota de voz melhora a demo.

O fetch do áudio recebido (`buscar_audio`) também é em dois GETs: `/{media_id}` devolve
uma `url` temporária (lookaside CDN), e o GET dessa url — também com o Bearer — devolve
os bytes, que é o que o `Transcritor` da Fase 6 espera.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Protocol

import httpx

logger = logging.getLogger("cb_amc_comercial.whatsapp")

_TIMEOUT_PADRAO = 30.0  # timeout explícito por requisição (segundos)


class EnvioWhatsApp(Protocol):
    """Porta que o dispatcher usa — permite injetar um fake nos testes."""

    async def enviar_texto(self, telefone: str, texto: str) -> bool: ...
    async def enviar_audio(self, telefone: str, audio: bytes) -> bool: ...
    async def enviar_documento(
        self,
        telefone: str,
        conteudo: bytes,
        *,
        filename: str,
        mimetype: str = "text/html",
        caption: str | None = None,
    ) -> bool: ...
    async def buscar_audio(self, mensagem: dict) -> bytes | None: ...


class WhatsAppCloudClient:
    """Cliente HTTP da Graph API (Cloud API oficial da Meta).

    `access_token` é o token permanente do System User (lido de settings).
    # TODO: aguardando token permanente da Meta — enquanto o .env tiver o placeholder,
    # as chamadas voltam 401 e degradam (log + False), sem derrubar o app.
    """

    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        access_token: str,
        phone_number_id: str,
        api_version: str = "v23.0",
        base_url: str = "https://graph.facebook.com",
        timeout: float = _TIMEOUT_PADRAO,
    ) -> None:
        self.http = http
        self.access_token = access_token
        self.phone_number_id = phone_number_id
        self.api_version = api_version
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    @property
    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}

    def _url(self, caminho: str) -> str:
        """URL do Graph: <base>/<versao>/<caminho>."""
        return f"{self.base_url}/{self.api_version}/{caminho}"

    @staticmethod
    def _normalizar(telefone: str) -> str:
        """E.164 sem o `+` (a Cloud API espera só dígitos no campo `to`)."""
        return (telefone or "").lstrip("+")

    async def _request(self, metodo: str, url: str, **kwargs: Any) -> httpx.Response | None:
        """Chamada genérica com timeout, log de tempo e tratamento tipado de erro.

        Degrada SEMPRE para None (rede fora, 401, 4xx/5xx) — nunca levanta (§15).
        """
        kwargs.setdefault("timeout", self.timeout)
        kwargs.setdefault("headers", {}).update(self._auth_headers)
        inicio = time.monotonic()
        try:
            resp = await self.http.request(metodo, url, **kwargs)
        except Exception as exc:  # noqa: BLE001 - Meta fora/erro de rede: degrada, não derruba (§15)
            ms = (time.monotonic() - inicio) * 1000
            logger.warning("cloud api %s erro de rede (%.0fms): %s", metodo, ms, str(exc)[:120])
            return None
        ms = (time.monotonic() - inicio) * 1000
        if resp.status_code == 401:
            # Token inválido/expirado — provável placeholder ou token revogado.
            logger.error("cloud api 401 token inválido/expirado em %s (%.0fms)", metodo, ms)
            return None
        if resp.status_code >= 400:
            logger.warning(
                "cloud api %s -> %d (%.0fms): %s", metodo, resp.status_code, ms, resp.text[:160]
            )
            return None
        logger.info("cloud api %s -> %d (%.0fms)", metodo, resp.status_code, ms)
        return resp

    async def _enviar_mensagem(self, payload: dict[str, Any]) -> bool:
        """POST em /{phone_number_id}/messages (corpo JSON). True se 2xx."""
        url = self._url(f"{self.phone_number_id}/messages")
        resp = await self._request("POST", url, json=payload)
        return resp is not None

    async def _upload_media(self, conteudo: bytes, *, filename: str, mimetype: str) -> str | None:
        """Passo 1 da mídia: upload multipart -> media_id. None em falha."""
        url = self._url(f"{self.phone_number_id}/media")
        resp = await self._request(
            "POST",
            url,
            data={"messaging_product": "whatsapp", "type": mimetype},
            files={"file": (filename, conteudo, mimetype)},
        )
        if resp is None:
            return None
        try:
            return (resp.json() or {}).get("id")
        except Exception:  # noqa: BLE001 - resposta sem JSON válido -> degrada p/ None
            return None

    async def enviar_texto(self, telefone: str, texto: str) -> bool:
        return await self._enviar_mensagem(
            {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": self._normalizar(telefone),
                "type": "text",
                "text": {"body": texto},
            }
        )

    async def enviar_audio(self, telefone: str, audio: bytes) -> bool:
        """Envia o MP3 (audio/mpeg) como `type:audio`. Upload -> media_id -> mensagem."""
        media_id = await self._upload_media(audio, filename="resposta.mp3", mimetype="audio/mpeg")
        if not media_id:
            return False
        return await self._enviar_mensagem(
            {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": self._normalizar(telefone),
                "type": "audio",
                "audio": {"id": media_id},
            }
        )

    async def enviar_documento(
        self,
        telefone: str,
        conteudo: bytes,
        *,
        filename: str,
        mimetype: str = "text/html",
        caption: str | None = None,
    ) -> bool:
        """Envia um arquivo (ex.: HTML) como DOCUMENTO. Upload -> media_id -> mensagem.

        ADITIVO: degrada para False em erro — o texto já saiu antes (router.py)."""
        media_id = await self._upload_media(conteudo, filename=filename, mimetype=mimetype)
        if not media_id:
            return False
        documento: dict[str, Any] = {"id": media_id, "filename": filename}
        if caption is not None:
            documento["caption"] = caption
        return await self._enviar_mensagem(
            {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": self._normalizar(telefone),
                "type": "document",
                "document": documento,
            }
        )

    async def buscar_audio(self, mensagem: dict) -> bytes | None:
        """Recupera o áudio recebido. Dois GETs: /{media_id} -> url; url -> bytes.

        `mensagem` é o objeto da mensagem (entry...messages[i]) que tem `audio.id`.
        None se: sem media_id, info sem url, ou download falhar.
        # TODO: aguardando token permanente — sem token, os GETs voltam 401 -> None.
        """
        media_id = ((mensagem or {}).get("audio") or {}).get("id")
        if not media_id:
            return None
        info = await self._request("GET", self._url(media_id))
        if info is None:
            return None
        try:
            url = (info.json() or {}).get("url")
        except Exception:  # noqa: BLE001 - JSON inválido -> degrada
            return None
        if not url:
            return None
        binario = await self._request("GET", url)
        if binario is None:
            return None
        return binario.content

    async def aclose(self) -> None:
        await self.http.aclose()
