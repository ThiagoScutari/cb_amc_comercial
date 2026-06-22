"""Webhook do WhatsApp (Cloud API / Meta) + dispatcher — orquestra o fluxo ponta a ponta.

A AUTH é a PORTA ÚNICA (Fase 3): texto e ÁUDIO só chegam ao agente depois de
`SessaoAutenticada`; `Ferramentas` recebe o `cliente_id` da sessão, nunca do payload.
Garantia de saída: o TEXTO sai SEMPRE; o áudio é ADITIVO e best-effort (contrato da
Fase 7: áudio None ⇒ texto entregue). Espelho de canal (§8.3): áudio→áudio, texto→texto.

WEBHOOK DA CLOUD API — dois comportamentos no MESMO path:
- GET: verificação inicial. A Meta chama com `hub.mode`/`hub.verify_token`/`hub.challenge`.
  Token confere -> devolve o challenge (200, texto puro); senão 403.
- POST: recebimento. Payload `entry[].changes[].value.messages[]` (ver `extrair_mensagem`).
  Eventos de status (entregue/lido) chegam SEM `messages` (vêm em `statuses`) -> ignora.
  Não existe `fromMe`: as nossas próprias mensagens voltam como `statuses`, não `messages`,
  então não há eco a filtrar.

SEGURANÇA — assinatura do webhook (§6/§7): o header `X-Hub-Signature-256` é HMAC-SHA256
do corpo cru com o `WHATSAPP_APP_SECRET`. Validado ANTES de qualquer parse. Quando o
APP_SECRET ainda não foi preenchido (placeholder), a validação é PULADA com um WARNING
explícito — para não travar o dev/demo enquanto o segredo não chega. O `cliente_id`
continua vindo só da sessão (anti-IDOR), nunca do payload.

RESILIÊNCIA (§15):
- O webhook responde SEMPRE 200 em corpo malformado/JSON inválido p/ não disparar retry
  storm da Meta (assinatura inválida com secret configurado é a única exceção -> 403).
- O processamento real roda em BACKGROUND (ack imediato): como o LLM+TTS levam segundos,
  processar síncrono arriscaria timeout→reenvio.
- A task de background tem o SEU PRÓPRIO try/except amplo: depois do 200 o erro não tem
  mais pra onde voltar, então a task NUNCA pode crashar calada — loga + degrada.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import hmac
import json
import logging
from dataclasses import dataclass

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import PlainTextResponse

from app.agent.tools import Ferramentas
from app.auth.session import SessaoNegada, resolver_sessao
from app.config import Settings, get_settings
from app.data.repository import MockRepository
from app.ops.escalation import registrar_escalonamento
from app.report.resumo_pedidos import gerar_html_pedidos
from app.voice.fala import para_fala

logger = logging.getLogger("cb_amc_comercial.whatsapp")

# Emite o WARNING de "assinatura não validada" só UMA vez por processo (não a cada POST).
_aviso_assinatura_emitido = False

_MSG_AUDIO_RUIM = (
    "Não consegui entender o áudio. Pode repetir, por favor? Se preferir, é só mandar por escrito."
)

# ACK intermediário por TEMPO (§15, aditivo): se a resposta do agente demorar mais que o
# limiar, manda um aviso de espera ANTES da resposta real. Resposta rápida (ex.: "oi") não
# dispara ack. Falha no envio do ack é engolida — jamais bloqueia a resposta (como a voz).
_ACK_APOS_SEGUNDOS = 3.0  # limiar; sobreponível por instância (Dispatcher.ack_apos_segundos)
_MSG_ACK = "Só um instante, já estou verificando isso pra você 👍"

# Frases-gatilho (curadas, revisáveis) do resumo visual. Casam a intenção de "visão
# ampla" (plural/overview), não a consulta de UM pedido específico ("meu pedido 4471").
_GATILHOS_RESUMO = (
    "meus pedidos",
    "resumo de pedidos",
    "resumo dos pedidos",
    "status dos pedidos",
    "todos os pedidos",
    "lista de pedidos",
    "lista dos pedidos",
)


def _quer_resumo_visual(texto: str | None) -> bool:
    t = (texto or "").lower()
    return any(g in t for g in _GATILHOS_RESUMO)


@dataclass(frozen=True)
class MensagemRecebida:
    telefone: str  # E.164 sem `+` (campo `from`); o repo normaliza
    texto: str | None  # presente se for mensagem de texto
    audio_raw: dict | None  # a própria mensagem (tem `audio.id`) p/ buscar_audio, se for áudio

    @property
    def is_audio(self) -> bool:
        return self.audio_raw is not None


def extrair_mensagem(payload: dict) -> MensagemRecebida | None:
    """Parse defensivo do payload da Cloud API. None se: sem `messages` (evento de
    status), sem remetente, ou tipo não suportado. NUNCA levanta (malformado vira None).

    Estrutura: entry[].changes[].value.messages[] — cada mensagem tem `from`, `type` e
    o objeto do tipo (`text.body`, `audio.id`, ...).
    """
    try:
        for entry in payload.get("entry") or []:
            for change in entry.get("changes") or []:
                value = change.get("value") or {}
                mensagens = value.get("messages") or []
                if not mensagens:
                    continue  # evento de status (entregue/lido) -> ignora
                msg = mensagens[0]
                telefone = msg.get("from") or ""
                if not telefone:
                    continue
                tipo = msg.get("type")
                if tipo == "text":
                    texto = (msg.get("text") or {}).get("body")
                    if texto:
                        return MensagemRecebida(telefone=telefone, texto=texto, audio_raw=None)
                elif tipo == "audio":
                    # type:audio preparado p/ STT (Fase 6). audio_raw = a própria mensagem
                    # (tem `audio.id`), que buscar_audio usa nos dois GETs da mídia.
                    return MensagemRecebida(telefone=telefone, texto=None, audio_raw=msg)
                # imagem/figurinha/documento/etc. -> não suportado, ignora
        return None
    except Exception:  # noqa: BLE001 - payload malformado nunca derruba (§15)
        return None


def _assinatura_valida(corpo: bytes, header: str | None, app_secret: str) -> bool:
    """Valida o `X-Hub-Signature-256` (HMAC-SHA256 do corpo cru com o APP_SECRET).

    APP_SECRET vazio (placeholder) -> PULA a validação com um WARNING explícito (uma vez
    por processo), para não travar dev/demo. Com secret configurado, assinatura ausente
    ou divergente -> False (o webhook responde 403)."""
    global _aviso_assinatura_emitido
    if not app_secret:
        if not _aviso_assinatura_emitido:
            logger.warning("assinatura do webhook NÃO validada — APP_SECRET ausente")
            _aviso_assinatura_emitido = True
        return True
    if not header or not header.startswith("sha256="):
        return False
    esperado = "sha256=" + hmac.new(app_secret.encode(), corpo, hashlib.sha256).hexdigest()
    return hmac.compare_digest(esperado, header)


class Dispatcher:
    """Cola sessão (Fase 3) + agente (Fase 4) + voz (Fases 6/7) + Evolution.

    `sessionmaker` abre uma Session por mensagem; `repo_factory` a embrulha no
    repositório concreto (default `MockRepository`). Tudo INJETADO p/ testar com fakes.
    """

    def __init__(
        self,
        *,
        client,
        orquestrador,
        transcritor,
        sintetizador,
        sessionmaker,
        repo_factory=MockRepository,
    ) -> None:
        self.client = client
        self.orquestrador = orquestrador
        self.transcritor = transcritor
        self.sintetizador = sintetizador
        self.sessionmaker = sessionmaker
        self.repo_factory = repo_factory
        self.ack_apos_segundos = _ACK_APOS_SEGUNDOS  # limiar do ack; testes sobrepõem

    async def processar(self, payload: dict) -> None:
        """Entrada da task de background. try/except amplo: pós-200 o erro não volta
        a lugar nenhum, então NUNCA pode crashar calada — loga + degrada."""
        try:
            await self._processar(payload)
        except Exception as exc:  # noqa: BLE001 - robustez da task: nada escapa depois do 200 (§15)
            registrar_escalonamento("erro_dispatcher", None, str(exc))

    async def _processar(self, payload: dict) -> None:
        msg = extrair_mensagem(payload)
        if msg is None:  # eco / malformado / tipo não suportado
            return
        with self.sessionmaker() as session:
            repo = self.repo_factory(session)
            sessao = resolver_sessao(msg.telefone, repo)
            if isinstance(sessao, SessaoNegada):  # PORTA ÚNICA: nega -> escala, NUNCA agente
                registrar_escalonamento(sessao.motivo, None, "auth negada no webhook")
                await self.client.enviar_texto(msg.telefone, sessao.mensagem)
                return
            ferramentas = Ferramentas(repo, sessao.cliente_id)  # cliente_id só do código
            origem_audio = msg.is_audio
            if origem_audio:
                audio_in = await self.client.buscar_audio(msg.audio_raw)
                texto = await self.transcritor.transcrever(audio_in) if audio_in else None
                if not texto:  # mídia não baixou / inintelígivel -> pede p/ repetir
                    await self.client.enviar_texto(msg.telefone, _MSG_AUDIO_RUIM)
                    return
            else:
                texto = msg.texto
            # ACK por tempo: corrida entre o ack (dispara após o limiar) e o responder().
            # Resposta < limiar -> cancela o ack (cliente não recebe). >= limiar -> ack já saiu.
            # try/finally garante o cancelamento mesmo se responder() levantar.
            ack_task = asyncio.create_task(self._ack_apos_intervalo(msg.telefone))
            try:
                resposta = await self.orquestrador.responder(
                    ferramentas,
                    sessao.cliente_id,
                    texto,
                    nome=sessao.nome,
                    origem_audio=origem_audio,
                )
            finally:
                await self._cancelar_ack(ack_task)
            await self.client.enviar_texto(msg.telefone, resposta)  # TEXTO SEMPRE (a garantia)
            if origem_audio:  # espelha o canal (§8.3): áudio entra -> áudio sai (best-effort)
                # Texto formatado -> falável (números/datas por extenso) ANTES do TTS.
                # MESMO conteúdo, só a forma muda (porta única). para_fala degrada sozinho.
                audio_out = await self.sintetizador.sintetizar(para_fala(resposta))
                if audio_out:  # áudio None ⇒ o texto JÁ saiu acima (contrato Fase 7)
                    await self.client.enviar_audio(msg.telefone, audio_out)
            # ADITIVO: resumo visual em HTML (diferencial da demo). Roda DEPOIS do texto
            # já garantido; QUALQUER falha (geração ou envio) degrada em silêncio — o
            # cliente já recebeu a resposta em texto (listando os pedidos). Nunca quebra.
            if _quer_resumo_visual(texto):
                await self._enviar_resumo_html(msg.telefone, repo, sessao.cliente_id, sessao.nome)

    async def _ack_apos_intervalo(self, telefone: str) -> None:
        """Espera o limiar e SÓ ENTÃO envia o ack de espera. Cancelado se a resposta vier
        antes (o sleep levanta CancelledError, que propaga e encerra a task sem enviar nada).
        ADITIVO: falha no envio do ack é engolida — nunca bloqueia a resposta real (§15)."""
        await asyncio.sleep(self.ack_apos_segundos)  # fora do try: cancelar aqui = não enviar
        try:
            await self.client.enviar_texto(telefone, _MSG_ACK)
        except Exception as exc:  # noqa: BLE001 - ack é aditivo; falha não bloqueia a resposta (§15)
            logger.warning("ack de espera falhou (aditivo, ignorado): %s", str(exc)[:120])

    @staticmethod
    async def _cancelar_ack(task: asyncio.Task) -> None:
        """Cancela a task de ack e absorve o CancelledError. Resposta < limiar: o ack é
        cancelado em pleno sleep (nunca enviado). Resposta >= limiar: a task já terminou
        (ack enviado), o cancel é no-op e o await retorna na hora. Ack: no máximo uma vez."""
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def _enviar_resumo_html(self, telefone, repo, cliente_id: int, nome: str | None) -> None:
        """Gera e envia o resumo visual (HTML/documento). ADITIVO e best-effort: todo o
        corpo é envolto em try/except — falha de geração ou de envio NÃO derruba o fluxo
        (o texto já saiu). anti-IDOR: listar_pedidos filtra pelo cliente_id da sessão."""
        try:
            pedidos = repo.listar_pedidos(cliente_id)  # só os pedidos deste cliente
            html = gerar_html_pedidos(nome or "Cliente", pedidos)
            await self.client.enviar_documento(
                telefone,
                html.encode("utf-8"),
                filename="Resumo de Pedidos.html",
                caption="Aqui está o resumo dos seus pedidos.",
            )
        except Exception as exc:  # noqa: BLE001 - ADITIVO: o HTML nunca pode derrubar o fluxo (§15)
            logger.warning("resumo HTML falhou (aditivo, ignorado): %s", str(exc)[:120])

    async def aclose(self) -> None:
        fechar = getattr(self.client, "aclose", None)
        if fechar is not None:
            await fechar()


def criar_router(settings: Settings | None = None) -> APIRouter:
    """Router do webhook. Lê o Dispatcher de `app.state.dispatcher` (montado no lifespan).

    `settings` (default `get_settings()`) fornece o `verify_token` (GET) e o `app_secret`
    (assinatura do POST). Injetável para testes."""
    s = settings or get_settings()
    router = APIRouter()

    @router.get("/webhook/whatsapp")
    async def verificar(request: Request) -> PlainTextResponse:
        """Verificação inicial da Cloud API: token confere -> devolve o challenge."""
        params = request.query_params
        if (
            params.get("hub.mode") == "subscribe"
            and s.whatsapp_verify_token
            and params.get("hub.verify_token") == s.whatsapp_verify_token
        ):
            return PlainTextResponse(params.get("hub.challenge") or "")
        return PlainTextResponse("forbidden", status_code=403)

    @router.post("/webhook/whatsapp")
    async def webhook(request: Request, background: BackgroundTasks) -> PlainTextResponse:
        corpo = await request.body()
        # Assinatura primeiro (sobre o corpo CRU). Inválida c/ secret configurado -> 403.
        if not _assinatura_valida(
            corpo, request.headers.get("X-Hub-Signature-256"), s.whatsapp_app_secret
        ):
            return PlainTextResponse("invalid signature", status_code=403)
        # Corpo não-JSON / não-objeto: 200 e ignora (sem 422 -> sem retry storm).
        try:
            payload = json.loads(corpo)
        except Exception:  # noqa: BLE001
            return PlainTextResponse("ignored")
        if not isinstance(payload, dict):
            return PlainTextResponse("ignored")
        dispatcher = getattr(request.app.state, "dispatcher", None)
        if dispatcher is not None:
            background.add_task(dispatcher.processar, payload)  # ack imediato; processa async
        return PlainTextResponse("received")

    return router
