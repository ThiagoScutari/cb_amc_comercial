"""Testes do webhook + dispatcher (Cloud API / Meta) — SEM Meta viva, SEM rede, SEM keys.

Tudo via fakes injetados (FakeWhatsAppClient + fakes de orquestrador/transcritor/
sintetizador + FakeRepo). Cobrem: parsing/roteamento da Cloud API, auth como PORTA ÚNICA
(áudio só após autenticar), contrato áudio-None⇒texto-entregue, robustez da task de
background, verificação GET do webhook e validação da assinatura (X-Hub-Signature-256).

O que depende da Cloud API viva (envio real/fetch real de mídia) NÃO é testado aqui — é
validação de host. O `WhatsAppCloudClient` é exercido via `httpx.MockTransport` (sem rede),
provando montagem de URL/payload/headers, o fluxo de mídia em dois passos e a degradação.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import hmac
import json
from pathlib import Path

import httpx
import pytest
from app.config import Settings
from app.whatsapp.client import WhatsAppCloudClient
from app.whatsapp.router import _MSG_ACK, Dispatcher, criar_router, extrair_mensagem
from fastapi import FastAPI
from fastapi.testclient import TestClient

_TEL = "5531988880002"  # E.164 sem `+` (campo `from` da Cloud API)
_FIXTURE = Path(__file__).parent / "fixtures" / "whatsapp_cloud_webhook_sample.json"


# ---------- fakes ----------
class FakeWhatsAppClient:
    def __init__(self, audio_in: bytes | None = b"ogg-bytes"):
        self.textos: list[tuple[str, str]] = []
        self.audios: list[tuple[str, bytes]] = []
        # (telefone, conteudo, filename, mimetype)
        self.documentos: list[tuple[str, bytes, str, str]] = []
        self.falha_documento = False  # True -> enviar_documento levanta (simula Meta fora)
        self.buscou = 0
        self._audio_in = audio_in

    async def enviar_texto(self, telefone, texto):
        self.textos.append((telefone, texto))
        return True

    async def enviar_audio(self, telefone, audio):
        self.audios.append((telefone, audio))
        return True

    async def enviar_documento(
        self, telefone, conteudo, *, filename, mimetype="text/html", caption=None
    ):
        if self.falha_documento:
            raise RuntimeError("cloud api media caiu")
        self.documentos.append((telefone, conteudo, filename, mimetype))
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
        self.textos: list[str] = []  # captura o que o TTS recebeu (prova do para_fala)

    async def sintetizar(self, texto):
        self.chamadas += 1
        self.textos.append(texto)
        return self.audio


class FakeCliente:
    def __init__(self, id=7, ativo=True, nome_fantasia="Loja Teste"):
        self.id = id
        self.ativo = ativo
        self.nome_fantasia = nome_fantasia


class FakeRepo:
    def __init__(self, cliente, pedidos=None, notas=None, titulos=None, devolucoes=None):
        self._cliente = cliente
        self._pedidos = pedidos or []
        self._notas = notas or []
        self._titulos = titulos or []
        self._devolucoes = devolucoes or []

    def cliente_por_telefone(self, telefone):
        return self._cliente

    def listar_pedidos(self, cliente_id, filtro_status=None):
        return self._pedidos  # já "filtrado": só os pedidos deste cliente

    def listar_notas_fiscais(self, cliente_id):
        return self._notas

    def listar_titulos(self, cliente_id, filtro_status=None):
        return self._titulos

    def listar_devolucoes(self, cliente_id):
        return self._devolucoes


@contextlib.contextmanager
def _sessionmaker_fake():
    yield object()  # sessão dummy; FakeRepo a ignora


_SEM_CLIENTE = object()  # sentinela: distingue "não passou" de "passou None" (desconhecido)


def _make(cliente=_SEM_CLIENTE, audio_in=b"ogg", texto_stt="cadê meu pedido", audio_out=b"mp3"):
    cliente = FakeCliente() if cliente is _SEM_CLIENTE else cliente
    client = FakeWhatsAppClient(audio_in=audio_in)
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


# ---------- builders de payload (formato Cloud API) ----------
def _envelope(message: dict | None, *, statuses: dict | None = None) -> dict:
    """Monta o envelope entry[].changes[].value. `message` None + statuses -> evento de status."""
    value: dict = {
        "messaging_product": "whatsapp",
        "metadata": {"display_phone_number": "15559576970", "phone_number_id": "PNID"},
    }
    if message is not None:
        value["contacts"] = [{"profile": {"name": "Loja Teste"}, "wa_id": message["from"]}]
        value["messages"] = [message]
    if statuses is not None:
        value["statuses"] = [statuses]
    return {
        "object": "whatsapp_business_account",
        "entry": [{"id": "WABA", "changes": [{"value": value, "field": "messages"}]}],
    }


def _texto_payload(texto="oi", wa_id=_TEL):
    return _envelope(
        {"from": wa_id, "id": "wamid.X", "timestamp": "1", "type": "text", "text": {"body": texto}}
    )


def _audio_payload(wa_id=_TEL, media_id="MEDIA123"):
    return _envelope(
        {
            "from": wa_id,
            "id": "wamid.A",
            "timestamp": "1",
            "type": "audio",
            "audio": {"id": media_id, "mime_type": "audio/ogg"},
        }
    )


def _status_payload(wa_id=_TEL):
    # Evento de status (entregue/lido) — vem SEM `messages`, em `statuses`.
    return _envelope(None, statuses={"id": "wamid.X", "status": "delivered", "recipient_id": wa_id})


# ---------- parsing ----------
def test_extrai_mensagem_de_texto():
    msg = extrair_mensagem(_texto_payload("meu pedido 4471 saiu?"))
    assert msg is not None and msg.telefone == _TEL
    assert msg.texto == "meu pedido 4471 saiu?" and not msg.is_audio


def test_extrai_mensagem_de_audio_guarda_a_mensagem_com_media_id():
    msg = extrair_mensagem(_audio_payload())
    assert msg is not None and msg.is_audio and msg.texto is None
    # audio_raw é a própria mensagem (tem audio.id) — é o que buscar_audio consome.
    assert msg.audio_raw["audio"]["id"] == "MEDIA123"


def test_extrai_mensagem_do_fixture_real():
    payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    msg = extrair_mensagem(payload)
    assert msg is not None and msg.telefone == _TEL
    assert msg.texto == "meu pedido 4471 saiu?"


def test_status_sem_messages_retorna_none():
    # Evento de entregue/lido não tem `messages` -> ignorado (não roteia pro agente).
    assert extrair_mensagem(_status_payload()) is None


def test_payload_malformado_retorna_none():
    assert extrair_mensagem({}) is None
    assert extrair_mensagem({"entry": []}) is None
    assert extrair_mensagem({"entry": [{"changes": [{"value": {}}]}]}) is None
    assert extrair_mensagem({"entry": [{"changes": [{"value": {"messages": [{}]}}]}]}) is None


def test_tipo_nao_suportado_retorna_none():
    img = _envelope(
        {"from": _TEL, "id": "wamid.I", "timestamp": "1", "type": "image", "image": {"id": "x"}}
    )
    assert extrair_mensagem(img) is None


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


async def test_status_event_no_dispatcher_nao_chama_agente_nem_envia():
    # Evento de status atravessa o dispatcher como no-op (extrair_mensagem -> None).
    disp, client, orq, stt, tts = _make()
    await disp.processar(_status_payload())
    assert orq.chamadas == [] and client.textos == [] and client.audios == []


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


async def test_audio_fala_por_extenso_texto_continua_formatado():
    # Porta única: o TEXTO sai formatado (dígitos); o ÁUDIO é o MESMO conteúdo, mas
    # números por extenso (para_fala roda entre responder() e sintetizar()).
    disp, client, orq, stt, tts = _make()
    orq.resposta = "Seu pedido tem 200 peças."
    await disp.processar(_audio_payload())
    assert client.textos == [(_TEL, "Seu pedido tem 200 peças.")]  # texto: formatado, verbatim
    assert tts.textos == ["Seu pedido tem duzentas peças."]  # áudio: derivado, por extenso


# ---------- resumo visual em PDF (aditivo) ----------
@pytest.fixture(autouse=True)
def _stub_html_para_pdf(monkeypatch):
    """WeasyPrint exige libs nativas (ausentes no dev Windows); o render real é validado no
    container. Aqui stubamos `html_para_pdf` p/ testar o ROTEAMENTO (mimetype/filename/best-
    effort) sem depender das libs — devolve um PDF mínimo (magic %PDF + um trecho do HTML)."""
    monkeypatch.setattr(
        "app.whatsapp.router.html_para_pdf",
        lambda html: b"%PDF-1.7\n" + html.encode("utf-8")[:48],
    )


def test_quer_resumo_visual_casa_frases_de_resumo():
    from app.whatsapp.router import _quer_resumo_visual

    for t in [
        "meus pedidos",
        "me manda o resumo dos pedidos",
        "qual o status dos pedidos?",
        "quero um resumo de pedidos",
        "todos os pedidos",
        "MEUS PEDIDOS",
    ]:
        assert _quer_resumo_visual(t) is True, t


def test_quer_resumo_visual_ignora_texto_comum():
    from app.whatsapp.router import _quer_resumo_visual

    for t in ["tem camiseta branca M?", "cadê meu pedido 4471", "oi", "quero cancelar o 4471", ""]:
        assert _quer_resumo_visual(t) is False, t


async def test_gatilho_resumo_envia_documento_alem_do_texto():
    disp, client, orq, stt, tts = _make()
    await disp.processar(_texto_payload("meus pedidos"))
    assert len(client.textos) == 1  # TEXTO sempre (a garantia)
    assert len(client.documentos) == 1  # + documento PDF (aditivo)
    tel, conteudo, fname, mime = client.documentos[0]
    assert tel == _TEL and fname.endswith(".pdf") and mime == "application/pdf"
    assert conteudo.startswith(b"%PDF")  # documento é PDF (Cloud API rejeita HTML)


async def test_sem_gatilho_nao_envia_documento():
    disp, client, orq, stt, tts = _make()
    await disp.processar(_texto_payload("tem camiseta branca M?"))
    assert len(client.documentos) == 0
    assert len(client.textos) == 1


async def test_documento_que_falha_nao_quebra_o_texto():
    # ADITIVO: se o envio do documento lança, o texto JÁ saiu e nada quebra (try/except amplo).
    disp, client, orq, stt, tts = _make()
    client.falha_documento = True
    await disp.processar(_texto_payload("meus pedidos"))
    assert len(client.textos) == 1  # texto entregue mesmo com o envio falhando
    assert len(client.documentos) == 0  # nada registrado (falhou e foi engolido)


async def test_pdf_que_falha_na_renderizacao_nao_quebra_o_texto(monkeypatch):
    # Se html_para_pdf lança (libs/render quebrados), o texto JÁ saiu e nada cai (best-effort).
    def _boom(_html):
        raise RuntimeError("weasyprint quebrou")

    monkeypatch.setattr("app.whatsapp.router.html_para_pdf", _boom)
    disp, client, orq, stt, tts = _make()
    await disp.processar(_texto_payload("meus pedidos"))
    assert len(client.textos) == 1  # texto entregue
    assert len(client.documentos) == 0  # render do PDF falhou e foi engolido


# ---------- S16: listas visuais de NF / título / devolução (aditivo) ----------
def test_entidade_visual_classifica_e_prioriza_pedidos():
    from app.whatsapp.router import _entidade_visual

    assert _entidade_visual("meus pedidos") == "pedidos"
    assert _entidade_visual("me manda minhas notas fiscais") == "notas"
    assert _entidade_visual("quero ver meus boletos") == "titulos"
    assert _entidade_visual("status das devoluções") == "devolucoes"
    assert _entidade_visual("oi, tudo bem?") is None
    # pedido tem PRIORIDADE quando dois gatilhos aparecem (sem colisão observável)
    assert _entidade_visual("meus pedidos e minhas notas") == "pedidos"


async def test_gatilho_notas_envia_documento():
    # FakeRepo devolve lista vazia -> só validamos o ROTEAMENTO (filename + HTML válido).
    # O conteúdo com dados reais é testado em test_resumo_pedidos.py (repo seedado).
    disp, client, orq, stt, tts = _make()
    await disp.processar(_texto_payload("me manda minhas notas fiscais"))
    assert len(client.textos) == 1
    tel, conteudo, fname, mime = client.documentos[0]
    assert fname == "notas_fiscais.pdf" and mime == "application/pdf"
    assert conteudo.startswith(b"%PDF")


async def test_gatilho_titulos_envia_documento():
    disp, client, orq, stt, tts = _make()
    await disp.processar(_texto_payload("quero ver meus boletos"))
    assert client.documentos[0][2] == "titulos.pdf"
    assert client.documentos[0][3] == "application/pdf"


async def test_gatilho_devolucoes_envia_documento():
    disp, client, orq, stt, tts = _make()
    await disp.processar(_texto_payload("status das devoluções"))
    assert client.documentos[0][2] == "devolucoes.pdf"


async def test_meus_pedidos_ainda_cai_em_pedidos_sem_colisao():
    disp, client, orq, stt, tts = _make()
    await disp.processar(_texto_payload("meus pedidos"))
    assert client.documentos[0][2] == "pedidos.pdf"


async def test_lista_html_que_falha_nao_quebra_o_texto():
    # o caminho novo (NF/título/devolução) degrada igual ao de pedidos.
    disp, client, orq, stt, tts = _make()
    client.falha_documento = True
    await disp.processar(_texto_payload("minhas notas fiscais"))
    assert len(client.textos) == 1
    assert len(client.documentos) == 0


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


# ---------- ack intermediário por tempo (>limiar) ----------
async def test_ack_resposta_rapida_nao_envia_ack():
    # responder() retorna na hora (< limiar) -> a task de ack é cancelada antes de disparar.
    disp, client, orq, stt, tts = _make()
    await disp.processar(_texto_payload("oi"))
    assert client.textos == [(_TEL, "resposta do agente")]  # só a resposta real, sem ack


async def test_ack_resposta_lenta_envia_ack_uma_vez_antes_da_resposta():
    # limiar zero -> o ack dispara assim que o responder cede o loop; chega ANTES da resposta.
    disp, client, orq, stt, tts = _make()
    disp.ack_apos_segundos = 0.0
    evento = asyncio.Event()

    class _OrqLento:
        async def responder(self, *a, **k):
            await evento.wait()  # trava até o teste liberar (depois de ver o ack)
            return "resposta real"

    disp.orquestrador = _OrqLento()
    task = asyncio.create_task(disp.processar(_texto_payload("demora pra verificar isso")))
    for _ in range(10):  # cede o loop até o ack aparecer (sem sleep real)
        await asyncio.sleep(0)
        if client.textos:
            break
    assert client.textos == [(_TEL, _MSG_ACK)]  # ack chegou primeiro, exatamente uma vez
    evento.set()  # libera a resposta real
    await task
    assert client.textos == [(_TEL, _MSG_ACK), (_TEL, "resposta real")]  # ack, depois a resposta


async def test_ack_que_falha_no_envio_nao_impede_a_resposta_real():
    # ack é aditivo: se enviar_texto do ack levanta, a resposta real ainda é entregue.
    class _ClienteAckFalha(FakeWhatsAppClient):
        async def enviar_texto(self, telefone, texto):
            if texto == _MSG_ACK:
                raise RuntimeError("ack caiu")
            return await super().enviar_texto(telefone, texto)

    client = _ClienteAckFalha()
    evento = asyncio.Event()

    class _OrqLento:
        async def responder(self, *a, **k):
            await evento.wait()
            return "resposta real"

    disp = Dispatcher(
        client=client,
        orquestrador=_OrqLento(),
        transcritor=FakeTranscritor(),
        sintetizador=FakeSintetizador(),
        sessionmaker=_sessionmaker_fake,
        repo_factory=lambda session: FakeRepo(FakeCliente()),
    )
    disp.ack_apos_segundos = 0.0
    task = asyncio.create_task(disp.processar(_texto_payload("demora pra verificar isso")))
    for _ in range(10):
        await asyncio.sleep(0)  # deixa o ack tentar (e falhar) antes de liberar a resposta
    evento.set()
    await task
    # ack falhou e foi engolido; a resposta real foi entregue mesmo assim
    assert client.textos == [(_TEL, "resposta real")]


# ---------- webhook HTTP: app de teste com settings injetadas ----------
class _StubDispatcher:
    def __init__(self):
        self.recebidos: list[dict] = []

    async def processar(self, payload):
        self.recebidos.append(payload)


def _app_teste(*, verify_token="", app_secret="", dispatcher=None) -> FastAPI:
    # _env_file=None -> determinístico (ignora qualquer .env do host).
    s = Settings(_env_file=None, whatsapp_verify_token=verify_token, whatsapp_app_secret=app_secret)
    a = FastAPI()
    a.state.dispatcher = dispatcher
    a.include_router(criar_router(s))
    return a


def _assinar(corpo: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), corpo, hashlib.sha256).hexdigest()


# ---------- GET de verificação ----------
def test_verify_get_token_correto_retorna_challenge():
    cli = TestClient(_app_teste(verify_token="segredo123"))
    r = cli.get(
        "/webhook/whatsapp",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "segredo123",
            "hub.challenge": "1234567890",
        },
    )
    assert r.status_code == 200 and r.text == "1234567890"


def test_verify_get_token_errado_retorna_403():
    cli = TestClient(_app_teste(verify_token="segredo123"))
    r = cli.get(
        "/webhook/whatsapp",
        params={"hub.mode": "subscribe", "hub.verify_token": "errado", "hub.challenge": "x"},
    )
    assert r.status_code == 403


def test_verify_get_token_nao_configurado_retorna_403():
    # verify_token vazio nunca casa (evita aceitar verificação sem token definido).
    cli = TestClient(_app_teste(verify_token=""))
    r = cli.get(
        "/webhook/whatsapp",
        params={"hub.mode": "subscribe", "hub.verify_token": "", "hub.challenge": "x"},
    )
    assert r.status_code == 403


# ---------- POST: assinatura ----------
def test_post_sem_secret_pula_validacao_e_agenda(caplog):
    # APP_SECRET ausente -> pula validação com WARNING explícito e segue (dev/demo).
    import app.whatsapp.router as router_mod

    router_mod._aviso_assinatura_emitido = False  # garante o WARNING neste teste
    stub = _StubDispatcher()
    cli = TestClient(_app_teste(app_secret="", dispatcher=stub))
    with caplog.at_level("WARNING"):
        r = cli.post("/webhook/whatsapp", json=_texto_payload("oi"))
    assert r.status_code == 200
    assert stub.recebidos == [_texto_payload("oi")]
    assert "APP_SECRET ausente" in caplog.text


def test_post_assinatura_valida_agenda_processamento():
    stub = _StubDispatcher()
    cli = TestClient(_app_teste(app_secret="sk-secret", dispatcher=stub))
    corpo = json.dumps(_texto_payload("oi")).encode("utf-8")
    r = cli.post(
        "/webhook/whatsapp",
        content=corpo,
        headers={"X-Hub-Signature-256": _assinar(corpo, "sk-secret")},
    )
    assert r.status_code == 200
    assert stub.recebidos == [_texto_payload("oi")]


def test_post_assinatura_invalida_retorna_403_e_nao_agenda():
    stub = _StubDispatcher()
    cli = TestClient(_app_teste(app_secret="sk-secret", dispatcher=stub))
    corpo = json.dumps(_texto_payload("oi")).encode("utf-8")
    r = cli.post(
        "/webhook/whatsapp",
        content=corpo,
        headers={"X-Hub-Signature-256": "sha256=deadbeef"},
    )
    assert r.status_code == 403
    assert stub.recebidos == []  # forjada -> nunca chega ao dispatcher


def test_post_assinatura_ausente_com_secret_configurado_retorna_403():
    stub = _StubDispatcher()
    cli = TestClient(_app_teste(app_secret="sk-secret", dispatcher=stub))
    r = cli.post("/webhook/whatsapp", json=_texto_payload("oi"))  # sem header
    assert r.status_code == 403
    assert stub.recebidos == []


# ---------- POST: resiliência ----------
def test_post_corpo_malformado_responde_200_e_nao_agenda():
    stub = _StubDispatcher()
    cli = TestClient(_app_teste(app_secret="", dispatcher=stub))
    r = cli.post(
        "/webhook/whatsapp", content=b"{nao eh json", headers={"content-type": "application/json"}
    )
    assert r.status_code == 200  # sem 422 -> sem retry storm
    assert stub.recebidos == []


def test_post_sem_dispatcher_montado_responde_200():
    cli = TestClient(_app_teste(app_secret="", dispatcher=None))
    r = cli.post("/webhook/whatsapp", json=_texto_payload("oi"))
    assert r.status_code == 200


# ---------- WhatsAppCloudClient (lógica nossa, via httpx.MockTransport — sem rede) ----------
# Testa montagem de URL/payload/headers, o fluxo de mídia em 2 passos e a degradação.
def _client(handler) -> WhatsAppCloudClient:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return WhatsAppCloudClient(
        http, access_token="TOK", phone_number_id="PNID", api_version="v23.0"
    )


async def test_enviar_texto_monta_url_payload_e_bearer():
    capturado = {}

    def handler(request):
        capturado["url"] = str(request.url)
        capturado["auth"] = request.headers.get("Authorization")
        capturado["json"] = json.loads(request.content)
        return httpx.Response(200, json={"messages": [{"id": "wamid.x"}]})

    cli = _client(handler)
    assert await cli.enviar_texto("+5531988880002", "oi") is True
    assert capturado["url"] == "https://graph.facebook.com/v23.0/PNID/messages"
    assert capturado["auth"] == "Bearer TOK"
    assert capturado["json"] == {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": "5531988880002",  # `+` removido
        "type": "text",
        "text": {"body": "oi"},
    }
    await cli.aclose()


async def test_enviar_audio_faz_upload_e_referencia_media_id():
    chamadas = []

    def handler(request):
        chamadas.append(str(request.url))
        if request.url.path.endswith("/media"):
            # multipart de upload: messaging_product no form + OGG/OPUS (ptt = nota de voz).
            assert b"whatsapp" in request.content
            assert b"audio/ogg" in request.content  # mimetype OPUS -> nota de voz
            assert b"resposta.ogg" in request.content  # filename .ogg
            return httpx.Response(200, json={"id": "MID-1"})
        body = json.loads(request.content)
        # voice:true marca como nota de voz (ptt) -> toca inline, não como arquivo p/ baixar
        assert body["type"] == "audio" and body["audio"] == {"id": "MID-1", "voice": True}
        return httpx.Response(200, json={"messages": [{"id": "wamid.x"}]})

    cli = _client(handler)
    assert await cli.enviar_audio(_TEL, b"\x00\x01mp3") is True
    assert chamadas == [
        "https://graph.facebook.com/v23.0/PNID/media",
        "https://graph.facebook.com/v23.0/PNID/messages",
    ]
    await cli.aclose()


async def test_enviar_audio_falha_no_upload_nao_envia_mensagem():
    chamadas = []

    def handler(request):
        chamadas.append(str(request.url))
        return httpx.Response(500, json={})  # upload falha

    cli = _client(handler)
    assert await cli.enviar_audio(_TEL, b"mp3") is False
    assert len(chamadas) == 1  # só tentou o upload; não mandou mensagem
    await cli.aclose()


async def test_enviar_documento_upload_e_envia_type_document():
    capturado = {}

    def handler(request):
        if request.url.path.endswith("/media"):
            return httpx.Response(200, json={"id": "DOC-1"})
        capturado["json"] = json.loads(request.content)
        return httpx.Response(200, json={"messages": [{"id": "x"}]})

    cli = _client(handler)
    ok = await cli.enviar_documento(
        _TEL, b"<html>x</html>", filename="Resumo.html", caption="Seu resumo"
    )
    assert ok is True
    j = capturado["json"]
    assert j["type"] == "document"
    assert j["document"] == {"id": "DOC-1", "filename": "Resumo.html", "caption": "Seu resumo"}
    await cli.aclose()


async def test_buscar_audio_dois_gets_devolve_bytes():
    audio = b"ogg-opus-bytes-do-whatsapp"

    def handler(request):
        if request.url.path.endswith("/MEDIA123"):
            return httpx.Response(200, json={"url": "https://lookaside.fbsbx.com/x"})
        # segundo GET (na url do lookaside) devolve os bytes binários.
        assert request.headers.get("Authorization") == "Bearer TOK"
        return httpx.Response(200, content=audio)

    cli = _client(handler)
    msg = {"audio": {"id": "MEDIA123"}}
    assert await cli.buscar_audio(msg) == audio
    await cli.aclose()


async def test_buscar_audio_sem_media_id_devolve_none():
    def handler(request):  # não deve ser chamado
        raise AssertionError("não deveria bater na rede")

    cli = _client(handler)
    assert await cli.buscar_audio({"type": "audio"}) is None
    await cli.aclose()


async def test_401_token_invalido_degrada_para_false():
    def handler(request):
        return httpx.Response(401, json={"error": {"message": "invalid token"}})

    cli = _client(handler)
    assert await cli.enviar_texto(_TEL, "oi") is False  # token placeholder -> degrada
    await cli.aclose()


async def test_erro_http_e_rede_degradam_sem_levantar():
    def handler(request):
        raise httpx.ConnectError("conexão recusada")

    cli = _client(handler)
    assert await cli.enviar_texto(_TEL, "oi") is False  # Meta fora -> não derruba
    assert await cli.buscar_audio({"audio": {"id": "X"}}) is None
    await cli.aclose()
