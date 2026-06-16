"""Testes do orquestrador (tool-use loop) — SEM rede e SEM API key.

Usa um FakeAnthropic injetado que devolve Messages pré-roteirizadas. Os blocos
tool_use/tool_result seguem o formato da Claude API (tool_use_id casado).
"""

from types import SimpleNamespace

import httpx
import pytest
from anthropic import APITimeoutError
from app.agent.orchestrator import (
    FALLBACK,
    MAX_ROUNDS,
    HistoricoMemoria,
    Orquestrador,
    _e_turno_user_real,
    _truncar,
)
from app.agent.tools import Ferramentas
from app.data.repository import MockRepository
from app.data.seed import popular

MODELO = "claude-sonnet-4-6"


# ---------- helpers de mensagens falsas ----------
def _texto(t):
    return SimpleNamespace(type="text", text=t)


def _tool(id_, name, inp):
    return SimpleNamespace(type="tool_use", id=id_, name=name, input=inp)


def _msg(content, stop_reason):
    return SimpleNamespace(content=content, stop_reason=stop_reason)


class _FakeMessages:
    def __init__(self, fila, capturas, erro):
        self._fila = fila
        self.capturas = capturas
        self._erro = erro

    async def create(self, **kwargs):
        # snapshot da lista de mensagens: o orquestrador reusa/muta a mesma lista.
        self.capturas.append({**kwargs, "messages": list(kwargs.get("messages", []))})
        if self._erro is not None:
            raise self._erro
        return self._fila.pop(0)


class FakeAnthropic:
    """Espelha o mínimo de client.messages.create que o orquestrador usa."""

    def __init__(self, respostas, erro=None):
        self.capturas: list[dict] = []
        self.messages = _FakeMessages(list(respostas), self.capturas, erro)


@pytest.fixture
def ferramentas(session):
    popular(session)
    session.flush()
    return Ferramentas(MockRepository(session), cliente_id=1)


def _orq(fake):
    return Orquestrador(fake, HistoricoMemoria(), model=MODELO)


# ---------- roteamento e formato ----------
async def test_roteia_para_ferramenta_correta(ferramentas):
    fake = FakeAnthropic(
        [
            _msg([_tool("t1", "consultar_pedido", {"numero_pedido": 4471})], "tool_use"),
            _msg([_texto("Seu pedido 4471 está confirmado.")], "end_turn"),
        ]
    )
    texto = await _orq(fake).responder(ferramentas, cliente_id=1, mensagem="cadê o 4471?")
    assert "confirmado" in texto.lower()
    # a 2ª chamada recebeu o tool_result com os dados do pedido
    tool_result = fake.capturas[1]["messages"][-1]["content"][0]
    assert tool_result["type"] == "tool_result"
    assert tool_result["tool_use_id"] == "t1"
    assert "4471" in tool_result["content"]


async def test_sem_tool_call_retorna_texto(ferramentas):
    fake = FakeAnthropic([_msg([_texto("Oi! Como posso ajudar?")], "end_turn")])
    texto = await _orq(fake).responder(ferramentas, cliente_id=1, mensagem="oi")
    assert texto == "Oi! Como posso ajudar?"
    assert len(fake.capturas) == 1  # uma única chamada


async def test_multiplas_tool_calls_em_um_turno(ferramentas):
    fake = FakeAnthropic(
        [
            _msg(
                [
                    _tool("t1", "consultar_pedido", {"numero_pedido": 4471}),
                    _tool("t2", "buscar_produto", {"texto_busca": "camiseta"}),
                ],
                "tool_use",
            ),
            _msg([_texto("Pronto.")], "end_turn"),
        ]
    )
    await _orq(fake).responder(ferramentas, cliente_id=1, mensagem="duas coisas")
    resultados = fake.capturas[1]["messages"][-1]["content"]
    assert len(resultados) == 2  # dois tool_result numa única mensagem user
    assert {r["tool_use_id"] for r in resultados} == {"t1", "t2"}


# ---------- segurança: cliente_id sempre da sessão ----------
async def test_cliente_id_do_modelo_e_ignorado(ferramentas):
    # modelo injeta cliente_id=999; deve ser DESCARTADO e usado o da sessão (1).
    fake = FakeAnthropic(
        [
            _msg(
                [_tool("t1", "consultar_pedido", {"numero_pedido": 4471, "cliente_id": 999})],
                "tool_use",
            ),
            _msg([_texto("ok")], "end_turn"),
        ]
    )
    await _orq(fake).responder(ferramentas, cliente_id=1, mensagem="meu 4471")
    tool_result = fake.capturas[1]["messages"][-1]["content"][0]
    # 4471 é do cliente 1; achou -> prova que 999 foi ignorado (sessão=1 usada)
    assert tool_result.get("is_error") is None
    assert "4471" in tool_result["content"]


# ---------- resiliência ----------
async def test_parametro_obrigatorio_faltante_vira_is_error(ferramentas):
    # consultar_pedido sem numero_pedido -> TypeError no handler -> is_error, sem travar.
    fake = FakeAnthropic(
        [
            _msg([_tool("t1", "consultar_pedido", {})], "tool_use"),
            _msg([_texto("Desculpe, qual o número do pedido?")], "end_turn"),
        ]
    )
    texto = await _orq(fake).responder(ferramentas, cliente_id=1, mensagem="meu pedido")
    tool_result = fake.capturas[1]["messages"][-1]["content"][0]
    assert tool_result["is_error"] is True
    assert texto  # o loop não derrubou; resposta final veio


async def test_tool_desconhecida_vira_is_error(ferramentas):
    fake = FakeAnthropic(
        [
            _msg([_tool("t1", "ferramenta_inexistente", {"x": 1})], "tool_use"),
            _msg([_texto("hmm")], "end_turn"),
        ]
    )
    await _orq(fake).responder(ferramentas, cliente_id=1, mensagem="?")
    tool_result = fake.capturas[1]["messages"][-1]["content"][0]
    assert tool_result["is_error"] is True
    assert "desconhecida" in tool_result["content"].lower()


async def test_timeout_da_api_degrada_sem_travar(ferramentas):
    erro = APITimeoutError(request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))
    fake = FakeAnthropic([], erro=erro)
    texto = await _orq(fake).responder(ferramentas, cliente_id=1, mensagem="oi")
    assert texto == FALLBACK


async def test_cap_de_rounds_encerra_com_fallback(ferramentas):
    # modelo sempre pede tool, nunca encerra -> para no MAX_ROUNDS.
    respostas = [
        _msg([_tool(f"t{i}", "buscar_produto", {"texto_busca": "x"})], "tool_use")
        for i in range(MAX_ROUNDS + 3)
    ]
    fake = FakeAnthropic(respostas)
    texto = await _orq(fake).responder(ferramentas, cliente_id=1, mensagem="loop")
    assert texto == FALLBACK
    assert len(fake.capturas) == MAX_ROUNDS


# ---------- histórico ----------
async def test_historico_persiste_entre_turnos(ferramentas):
    store = HistoricoMemoria()
    orq = Orquestrador(FakeAnthropic([_msg([_texto("primeira")], "end_turn")]), store, model=MODELO)
    await orq.responder(ferramentas, cliente_id=1, mensagem="oi")
    fake2 = FakeAnthropic([_msg([_texto("segunda")], "end_turn")])
    orq2 = Orquestrador(fake2, store, model=MODELO)
    await orq2.responder(ferramentas, cliente_id=1, mensagem="de novo")
    # a 2ª chamada já carrega o histórico da 1ª (4 msgs: user/assist/user/assist)
    assert len(fake2.capturas[0]["messages"]) >= 3


def test_nome_do_cliente_entra_so_no_primeiro_turno():
    historico_vazio: list = []
    primeiro = Orquestrador._primeiro_turno("oi", "Marina", historico_vazio)
    assert "Marina" in primeiro["content"]
    com_historico = [{"role": "user", "content": "x"}]
    segundo = Orquestrador._primeiro_turno("de novo", "Marina", com_historico)
    assert segundo["content"] == "de novo"  # sem nome a partir do 2º turno


def test_truncar_por_turnos_preserva_inicio_user():
    msgs = [
        {"role": "user", "content": "t1"},
        {"role": "assistant", "content": ["a1"]},
        {"role": "user", "content": "t2"},
        {"role": "assistant", "content": ["a2"]},
        {"role": "user", "content": "t3"},
        {"role": "assistant", "content": ["a3"]},
    ]
    out = _truncar(msgs, max_turnos=2)
    assert [m["content"] for m in out] == ["t2", ["a2"], "t3", ["a3"]]
    assert _e_turno_user_real(out[0])


def test_truncar_nao_quebra_par_tool():
    msgs = [
        {"role": "user", "content": "t1"},
        {"role": "assistant", "content": ["tool_use"]},
        {"role": "user", "content": ["tool_result"]},  # não é turno real de usuário
        {"role": "assistant", "content": ["final1"]},
        {"role": "user", "content": "t2"},
        {"role": "assistant", "content": ["final2"]},
    ]
    out = _truncar(msgs, max_turnos=1)
    assert out[0]["content"] == "t2"  # corta no último turno de usuário real, não no tool_result
