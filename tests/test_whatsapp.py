"""Testes do webhook + dispatcher (Fase 8) — SEM Evolution viva, SEM rede, SEM keys.

Tudo via fakes injetados (FakeEvolutionClient + fakes de orquestrador/transcritor/
sintetizador + FakeRepo). Cobrem: parsing/roteamento, auth como PORTA ÚNICA (áudio só
após autenticar), ANTI-ECO (fromMe), contrato áudio-None⇒texto-entregue, robustez da
task de background e o webhook respondendo SEMPRE 200.

O que depende de Evolution viva (conexão/QR/envio real/fetch real) NÃO é testado aqui
— é validação de host (ver relatório da fase).
"""

from __future__ import annotations

import base64
import contextlib
import json

import httpx
import pytest
from app.main import app
from app.whatsapp.client import EvolutionClient
from app.whatsapp.router import Dispatcher, extrair_mensagem
from fastapi.testclient import TestClient

_JID = "5531988880002@s.whatsapp.net"
_TEL = "5531988880002"


# ---------- fakes ----------
class FakeEvolutionClient:
    def __init__(self, audio_in: bytes | None = b"ogg-bytes"):
        self.textos: list[tuple[str, str]] = []
        self.audios: list[tuple[str, bytes]] = []
        self.buscou = 0
        self._audio_in = audio_in

    async def enviar_texto(self, telefone, texto):
        self.textos.append((telefone, texto))
        return True

    async def enviar_audio(self, telefone, audio):
        self.audios.append((telefone, audio))
        return True

    async def buscar_audio(self, mensagem):
        self.buscou += 1
        return self._audio_in


class FakeOrquestrador:
    def __init__(self, resposta="resposta do agente"):
        self.resposta = resposta
        self.chamadas: list[dict] = []

    async def responder(self, ferramentas, cliente_id, mensagem, nome=None, origem_audio=False):
        self.chamadas.append(
            {
                "cliente_id": cliente_id,
                "mensagem": mensagem,
                "nome": nome,
                "origem_audio": origem_audio,
            }
        )
        return self.resposta


class FakeTranscritor:
    def __init__(self, texto="cadê meu pedido 4471"):
        self.texto = texto
        self.chamadas = 0

    async def transcrever(self, audio, **kw):
        self.chamadas += 1
        return self.texto


class FakeSintetizador:
    def __init__(self, audio: bytes | None = b"mp3-bytes"):
        self.audio = audio
        self.chamadas = 0

    async def sintetizar(self, texto):
        self.chamadas += 1
        return self.audio


class FakeCliente:
    def __init__(self, id=7, ativo=True, nome_fantasia="Loja Teste"):
        self.id = id
        self.ativo = ativo
        self.nome_fantasia = nome_fantasia


class FakeRepo:
    def __init__(self, cliente):
        self._cliente = cliente

    def cliente_por_telefone(self, telefone):
        return self._cliente


@contextlib.contextmanager
def _sessionmaker_fake():
    yield object()  # sessão dummy; FakeRepo a ignora


_SEM_CLIENTE = object()  # sentinela: distingue "não passou" de "passou None" (desconhecido)


def _make(cliente=_SEM_CLIENTE, audio_in=b"ogg", texto_stt="cadê meu pedido", audio_out=b"mp3"):
    cliente = FakeCliente() if cliente is _SEM_CLIENTE else cliente
    client = FakeEvolutionClient(audio_in=audio_in)
    orq = FakeOrquestrador()
    stt = FakeTranscritor(texto_stt)
    tts = FakeSintetizador(audio_out)
    disp = Dispatcher(
        client=client,
        orquestrador=orq,
        transcritor=stt,
        sintetizador=tts,
        sessionmaker=_sessionmaker_fake,
        repo_factory=lambda session: FakeRepo(cliente),
    )
    return disp, client, orq, stt, tts


def _texto_payload(texto="oi", jid=_JID, from_me=False):
    return {
        "event": "messages.upsert",
        "data": {
            "key": {"remoteJid": jid, "fromMe": from_me},
            "message": {"conversation": texto},
        },
    }


def _audio_payload(jid=_JID):
    return {
        "event": "messages.upsert",
        "data": {
            "key": {"remoteJid": jid, "fromMe": False},
            "message": {"audioMessage": {"url": "enc://..."}},
        },
    }


# ---------- parsing ----------
def test_extrai_mensagem_de_texto():
    msg = extrair_mensagem(_texto_payload("meu pedido 4471 saiu?"))
    assert msg is not None and msg.telefone == _TEL
    assert msg.texto == "meu pedido 4471 saiu?" and not msg.is_audio


def test_extrai_mensagem_de_audio():
    msg = extrair_mensagem(_audio_payload())
    assert msg is not None and msg.is_audio and msg.texto is None


def test_anti_eco_from_me_retorna_none():
    # mensagem que NÓS mandamos -> ignorada (senão o bot conversaria consigo mesmo)
    assert extrair_mensagem(_texto_payload("eco do bot", from_me=True)) is None


def test_payload_malformado_retorna_none():
    assert extrair_mensagem({}) is None
    assert extrair_mensagem({"event": "messages.upsert"}) is None
    assert extrair_mensagem({"event": "messages.upsert", "data": {"key": {}}}) is None


def test_tipo_nao_suportado_e_evento_irrelevante_retornam_none():
    img = {
        "event": "messages.upsert",
        "data": {"key": {"remoteJid": _JID, "fromMe": False}, "message": {"imageMessage": {}}},
    }
    assert extrair_mensagem(img) is None
    assert extrair_mensagem({"event": "connection.update", "data": {}}) is None


# ---------- roteamento ----------
async def test_roteamento_texto_autenticado_chama_agente_e_envia_texto():
    disp, client, orq, stt, tts = _make()
    await disp.processar(_texto_payload("tem camiseta branca M?"))
    assert orq.chamadas == [
        {
            "cliente_id": 7,
            "mensagem": "tem camiseta branca M?",
            "nome": "Loja Teste",
            "origem_audio": False,
        }
    ]
    assert client.textos == [(_TEL, "resposta do agente")]
    assert client.audios == []  # texto entra -> só texto sai (espelho de canal)
    assert stt.chamadas == 0


async def test_roteamento_numero_desconhecido_escala_e_nunca_chama_agente():
    disp, client, orq, stt, tts = _make(cliente=None)  # repo não acha cliente
    await disp.processar(_texto_payload("oi"))
    assert orq.chamadas == []  # PORTA ÚNICA: negada -> nunca o agente
    assert len(client.textos) == 1 and "identificar" in client.textos[0][1].lower()


async def test_roteamento_cliente_inativo_escala_e_nao_chama_agente():
    disp, client, orq, stt, tts = _make(cliente=FakeCliente(ativo=False))
    await disp.processar(_texto_payload("oi"))
    assert orq.chamadas == []
    assert len(client.textos) == 1 and "inativo" in client.textos[0][1].lower()


# ---------- auth-gate do ÁUDIO ----------
async def test_auth_gate_audio_numero_desconhecido_nao_transcreve_nem_agente():
    # áudio NÃO escapa da auth: número desconhecido nunca é transcrito nem chega ao agente
    disp, client, orq, stt, tts = _make(cliente=None)
    await disp.processar(_audio_payload())
    assert client.buscou == 0 and stt.chamadas == 0 and orq.chamadas == []
    assert len(client.textos) == 1  # só a mensagem de escalonamento


async def test_audio_autenticado_transcreve_responde_e_espelha_audio():
    disp, client, orq, stt, tts = _make()
    await disp.processar(_audio_payload())
    assert client.buscou == 1 and stt.chamadas == 1
    assert orq.chamadas[0]["origem_audio"] is True  # ativa o read-back de números
    assert client.textos == [(_TEL, "resposta do agente")]  # TEXTO sempre
    assert client.audios == [(_TEL, b"mp3")]  # áudio entra -> áudio sai


async def test_audio_que_nao_baixa_pede_para_repetir_sem_chamar_agente():
    disp, client, orq, stt, tts = _make(audio_in=None)  # buscar_audio devolve None
    await disp.processar(_audio_payload())
    assert orq.chamadas == [] and stt.chamadas == 0
    assert len(client.textos) == 1 and "áudio" in client.textos[0][1].lower()


async def test_audio_ininteligivel_pede_para_repetir_sem_chamar_agente():
    disp, client, orq, stt, tts = _make()
    stt.texto = None  # transcrição vazia/None
    await disp.processar(_audio_payload())
    assert orq.chamadas == []
    assert len(client.textos) == 1 and "áudio" in client.textos[0][1].lower()


# ---------- contrato da Fase 7 ----------
async def test_contrato_audio_none_texto_entregue_mesmo_assim():
    # TTS falha (None) -> o cliente AINDA recebe a resposta escrita; bot nunca fica mudo.
    disp, client, orq, stt, tts = _make(audio_out=None)
    await disp.processar(_audio_payload())
    assert client.textos == [(_TEL, "resposta do agente")]  # texto entregue
    assert client.audios == []  # nenhum áudio, e nenhuma exceção


# ---------- robustez da task de background ----------
class _OrqQueExplode:
    async def responder(self, *a, **k):
        raise RuntimeError("LLM caiu no meio")


async def test_task_background_nunca_crasha_silenciosamente():
    # pós-200 o erro não tem pra onde voltar: processar() degrada e NUNCA propaga.
    disp, client, orq, stt, tts = _make()
    disp.orquestrador = _OrqQueExplode()
    await disp.processar(_texto_payload("oi"))  # não deve levantar


# ---------- webhook responde SEMPRE 200 ----------
class _StubDispatcher:
    def __init__(self):
        self.recebidos: list[dict] = []

    async def processar(self, payload):
        self.recebidos.append(payload)


def test_resiliencia_webhook_200_valido_agenda_processamento():
    stub = _StubDispatcher()
    app.state.dispatcher = stub
    cli = TestClient(app)
    r = cli.post("/webhook/whatsapp", json=_texto_payload("oi"))
    assert r.status_code == 200
    assert stub.recebidos == [_texto_payload("oi")]  # task de background rodou


def test_resiliencia_webhook_200_corpo_malformado_nao_agenda():
    stub = _StubDispatcher()
    app.state.dispatcher = stub
    cli = TestClient(app)
    r = cli.post(
        "/webhook/whatsapp", content=b"{nao eh json", headers={"content-type": "application/json"}
    )
    assert r.status_code == 200  # sem 422 -> sem retry storm
    assert stub.recebidos == []


def test_resiliencia_webhook_200_sem_dispatcher_montado():
    app.state.dispatcher = None  # falha de init no lifespan não pode quebrar o webhook
    cli = TestClient(app)
    r = cli.post("/webhook/whatsapp", json=_texto_payload("oi"))
    assert r.status_code == 200


@pytest.fixture(autouse=True)
def _reset_dispatcher():
    yield
    app.state.dispatcher = None  # não vaza estado entre testes


# ---------- EvolutionClient (lógica nossa, via httpx.MockTransport — sem rede) ----------
# Testa montagem de URL/payload/header, base64 e degradação. NÃO testa Evolution viva.
def _client(handler) -> EvolutionClient:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return EvolutionClient(http, base_url="http://evo:8080", apikey="K", instancia="inst")


async def test_enviar_texto_monta_url_payload_e_apikey():
    capturado = {}

    def handler(request):
        capturado["url"] = str(request.url)
        capturado["apikey"] = request.headers.get("apikey")
        capturado["json"] = json.loads(request.content)
        return httpx.Response(200, json={"key": {"id": "x"}})

    cli = _client(handler)
    assert await cli.enviar_texto("5531988880002", "oi") is True
    assert capturado["url"] == "http://evo:8080/message/sendText/inst"
    assert capturado["apikey"] == "K"
    assert capturado["json"] == {"number": "5531988880002", "text": "oi"}
    await cli.aclose()


async def test_enviar_audio_manda_base64():
    capturado = {}

    def handler(request):
        capturado["json"] = json.loads(request.content)
        return httpx.Response(200, json={})

    cli = _client(handler)
    assert await cli.enviar_audio("5531988880002", b"\x00\x01mp3") is True
    assert capturado["json"]["audio"] == base64.b64encode(b"\x00\x01mp3").decode("ascii")
    await cli.aclose()


async def test_buscar_audio_decodifica_base64_para_bytes():
    audio = b"ogg-opus-bytes-do-whatsapp"

    def handler(request):
        return httpx.Response(200, json={"base64": base64.b64encode(audio).decode("ascii")})

    cli = _client(handler)
    assert await cli.buscar_audio({"key": {}}) == audio
    await cli.aclose()


async def test_erro_http_degrada_sem_levantar():
    def handler(request):
        return httpx.Response(500, json={"error": "boom"})

    cli = _client(handler)
    assert await cli.enviar_texto("5531988880002", "oi") is False
    assert await cli.buscar_audio({"key": {}}) is None  # falha -> None, não exceção
    await cli.aclose()


async def test_evolution_fora_do_ar_degrada_sem_levantar():
    def handler(request):
        raise httpx.ConnectError("conexão recusada")

    cli = _client(handler)
    assert await cli.enviar_texto("5531988880002", "oi") is False  # Evolution fora -> não derruba
    await cli.aclose()
