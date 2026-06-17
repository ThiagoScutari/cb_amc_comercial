"""Webhook do WhatsApp (Evolution) + dispatcher — orquestra o fluxo ponta a ponta.

A AUTH é a PORTA ÚNICA (Fase 3): texto e ÁUDIO só chegam ao agente depois de
`SessaoAutenticada`; `Ferramentas` recebe o `cliente_id` da sessão, nunca do payload.
Garantia de saída: o TEXTO sai SEMPRE; o áudio é ADITIVO e best-effort (contrato da
Fase 7: áudio None ⇒ texto entregue). Espelho de canal (§8.3): áudio→áudio, texto→texto.

RESILIÊNCIA (§15):
- O webhook responde SEMPRE 200 (mesmo corpo malformado) p/ não disparar retry storm
  da Evolution.
- O processamento real roda em BACKGROUND (ack imediato): como o LLM+TTS levam segundos,
  processar síncrono arriscaria timeout→reenvio.
- A task de background tem o SEU PRÓPRIO try/except amplo: depois do 200 o erro não tem
  mais pra onde voltar, então a task NUNCA pode crashar calada — loga + degrada.
- Anti-eco: mensagem `fromMe=true` (nossa própria) é ignorada, senão o bot conversaria
  consigo mesmo num loop.

DÍVIDA DE SEGURANÇA CONSCIENTE (F1): o webhook é um POST PÚBLICO SEM autenticação no
MVP. Um shared-secret em header (validado aqui) é trivial e deve entrar na V2. Está
ADIADO COM CONSCIÊNCIA, não resolvido.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from fastapi import APIRouter, BackgroundTasks, Request

from app.agent.tools import Ferramentas
from app.auth.session import SessaoNegada, resolver_sessao
from app.data.repository import MockRepository
from app.ops.escalation import registrar_escalonamento
from app.report.resumo_pedidos import gerar_html_pedidos
from app.voice.fala import para_fala

logger = logging.getLogger("cb_amc_comercial.whatsapp")

_MSG_AUDIO_RUIM = (
    "Não consegui entender o áudio. Pode repetir, por favor? Se preferir, é só mandar por escrito."
)

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
    telefone: str  # cru (remoteJid sem o sufixo); o repo normaliza
    texto: str | None  # presente se for mensagem de texto
    audio_raw: dict | None  # o objeto `data` p/ buscar_audio, se for áudio

    @property
    def is_audio(self) -> bool:
        return self.audio_raw is not None


def extrair_mensagem(payload: dict) -> MensagemRecebida | None:
    """Parse defensivo. None se: não é messages.upsert, é eco nosso (fromMe), sem
    remetente, ou tipo não suportado. NUNCA levanta (payload malformado vira None)."""
    try:
        if payload.get("event") not in ("messages.upsert", "MESSAGES_UPSERT"):
            return None
        data = payload.get("data") or {}
        key = data.get("key") or {}
        if key.get("fromMe") is True:  # ANTI-ECO: nossa própria mensagem -> ignora (evita loop)
            return None
        telefone = (key.get("remoteJid") or "").split("@", 1)[0]
        if not telefone:
            return None
        msg = data.get("message") or {}
        if msg.get("audioMessage"):
            return MensagemRecebida(telefone=telefone, texto=None, audio_raw=data)
        texto = msg.get("conversation") or (msg.get("extendedTextMessage") or {}).get("text")
        if texto:
            return MensagemRecebida(telefone=telefone, texto=texto, audio_raw=None)
        return None  # imagem/figurinha/etc. -> não suportado, ignora
    except Exception:  # noqa: BLE001 - payload malformado nunca derruba (§15)
        return None


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
            resposta = await self.orquestrador.responder(
                ferramentas,
                sessao.cliente_id,
                texto,
                nome=sessao.nome,
                origem_audio=origem_audio,
            )
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


def criar_router() -> APIRouter:
    """Router do webhook. Lê o Dispatcher de `app.state.dispatcher` (montado no lifespan)."""
    router = APIRouter()

    @router.post("/webhook/whatsapp")
    async def webhook(request: Request, background: BackgroundTasks) -> dict[str, str]:
        # Corpo não-JSON / não-objeto: 200 e ignora (sem 422 -> sem retry storm).
        try:
            payload = await request.json()
        except Exception:  # noqa: BLE001
            return {"status": "ignored"}
        if not isinstance(payload, dict):
            return {"status": "ignored"}
        dispatcher = getattr(request.app.state, "dispatcher", None)
        if dispatcher is not None:
            background.add_task(dispatcher.processar, payload)  # ack imediato; processa async
        return {"status": "received"}

    return router
