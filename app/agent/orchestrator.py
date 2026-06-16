"""Orquestrador do agente: loop de tool-use (texto) com a Claude API.

Liga a sessão (Fase 3 → `cliente_id`) às ferramentas (Fase 2). O `cliente_id`
vem SEMPRE de `Ferramentas` (código), NUNCA do modelo: os schemas em `TOOL_DEFS`
não têm `cliente_id`, e o dispatcher filtra as chaves que o modelo manda — qualquer
`cliente_id` injetado é descartado (princípio 2).

Loop manual (controle fino): chama Claude → executa as tool-calls → devolve os
`tool_result` numa única mensagem `user` → itera até `end_turn` ou `MAX_ROUNDS`.
Qualquer erro de API ou de ferramenta degrada com elegância (§15) — nunca derruba o bot.

Modelo: `claude-sonnet-4-6` (spec). O client (`AsyncAnthropic`) é INJETADO — os
testes passam um fake, então o CI roda sem rede e sem API key.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from anthropic import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    RateLimitError,
)
from pydantic import BaseModel

from app.agent.tools import NOMES_TOOLS, PARAMS_TOOLS, TOOL_DEFS, Ferramentas
from app.config import get_settings

SYSTEM_PROMPT = (Path(__file__).parent / "prompts" / "system_prompt.md").read_text(encoding="utf-8")
MAX_ROUNDS = 5  # cap anti-loop de tool-use
MAX_TOKENS = 1024  # respostas falável são curtas
FALLBACK = (
    "Tive um probleminha técnico aqui. Pode repetir, por favor? "
    "Se continuar, já te passo pra uma pessoa do nosso time."
)

Mensagem = dict
_ERROS_API = (APITimeoutError, RateLimitError, APIConnectionError, APIStatusError)


# ---------- histórico (plugável) ----------
class HistoricoStore(Protocol):
    """Porta do histórico, keyed por cliente_id. Troca de impl sem tocar no orquestrador."""

    def historico(self, cliente_id: int) -> list[Mensagem]: ...
    def registrar(self, cliente_id: int, novas: list[Mensagem]) -> None: ...


class HistoricoMemoria:
    """Impl em memória (MVP). Guarda os últimos `max_turnos` turnos por cliente.

    GATILHO DE TROCA (dívida consciente p/ Fase 8/deploy): num deploy multi-worker do
    uvicorn este dict NÃO é compartilhado entre processos — cada worker teria histórico
    próprio. Trocar por uma impl Postgres (mesma interface `HistoricoStore`) na produção,
    sem alterar o `Orquestrador`.
    """

    def __init__(self, max_turnos: int = 4) -> None:
        self._por_cliente: dict[int, list[Mensagem]] = {}
        self.max_turnos = max_turnos

    def historico(self, cliente_id: int) -> list[Mensagem]:
        return list(self._por_cliente.get(cliente_id, []))

    def registrar(self, cliente_id: int, novas: list[Mensagem]) -> None:
        atual = self._por_cliente.get(cliente_id, []) + list(novas)
        self._por_cliente[cliente_id] = _truncar(atual, self.max_turnos)


def _e_turno_user_real(m: Mensagem) -> bool:
    # turno "real" do usuário = role user com texto (não um tool_result solto).
    return m["role"] == "user" and isinstance(m["content"], str)


def _truncar(msgs: list[Mensagem], max_turnos: int) -> list[Mensagem]:
    """Mantém os últimos `max_turnos` turnos. Corta SEMPRE numa fronteira de turno de
    usuário real — começa em `user` e nunca quebra um par tool_use/tool_result."""
    inicios = [i for i, m in enumerate(msgs) if _e_turno_user_real(m)]
    if len(inicios) <= max_turnos:
        return list(msgs)
    return msgs[inicios[-max_turnos] :]


# ---------- orquestrador ----------
class Orquestrador:
    def __init__(self, client, store: HistoricoStore, model: str | None = None) -> None:
        self.client = client
        self.store = store
        self.model = model or get_settings().agent_model

    @staticmethod
    def _primeiro_turno(mensagem: str, nome: str | None, historico: list[Mensagem]) -> Mensagem:
        # Nome (da sessão) só no 1º turno, como linha de contexto — mantém o system
        # prompt estável/cacheável (não põe nome nem cliente_id no system).
        if nome and not historico:
            return {"role": "user", "content": f"[Cliente identificado: {nome}]\n{mensagem}"}
        return {"role": "user", "content": mensagem}

    async def responder(
        self,
        ferramentas: Ferramentas,
        cliente_id: int,
        mensagem: str,
        nome: str | None = None,
    ) -> str:
        historico = self.store.historico(cliente_id)
        msgs = historico + [self._primeiro_turno(mensagem, nome, historico)]

        resp = None
        sucesso = False
        for _ in range(MAX_ROUNDS):
            resp = await self._chamar(msgs)
            if resp is None:  # erro de API -> fallback, não persiste parcial
                return FALLBACK
            if resp.stop_reason != "tool_use":
                msgs.append({"role": "assistant", "content": resp.content})
                sucesso = True
                break
            msgs.append({"role": "assistant", "content": resp.content})
            resultados = [
                self._executar(ferramentas, b) for b in resp.content if b.type == "tool_use"
            ]
            msgs.append({"role": "user", "content": resultados})

        if not sucesso:  # cap estourado: degrada, não persiste turno incompleto
            return FALLBACK

        self.store.registrar(cliente_id, msgs[len(historico) :])
        return _texto_final(resp)

    async def _chamar(self, msgs: list[Mensagem]):
        try:
            return await self.client.messages.create(
                model=self.model,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                tools=TOOL_DEFS,
                messages=msgs,
            )
        except _ERROS_API:  # degrada: timeout/rate-limit/erro de servidor -> fallback
            return None

    def _executar(self, ferramentas: Ferramentas, bloco) -> Mensagem:
        if bloco.name not in NOMES_TOOLS:
            return _tool_result(bloco.id, "Ferramenta desconhecida.", erro=True)
        try:
            # filtra as chaves: só os parâmetros do schema passam (descarta cliente_id et al.)
            args = {k: bloco.input[k] for k in PARAMS_TOOLS[bloco.name] if k in bloco.input}
            handler = getattr(ferramentas, bloco.name)  # cliente_id vem de `ferramentas`
            return _tool_result(bloco.id, _serializa(handler(**args)))
        except Exception as exc:  # noqa: BLE001 - degradação: nada de tool derruba o loop
            return _tool_result(bloco.id, f"Erro ao executar a ferramenta: {exc}", erro=True)


def _tool_result(tool_use_id: str, content: str, erro: bool = False) -> Mensagem:
    bloco: Mensagem = {"type": "tool_result", "tool_use_id": tool_use_id, "content": content}
    if erro:
        bloco["is_error"] = True
    return bloco


def _serializa(vista) -> str:
    if isinstance(vista, BaseModel):
        return vista.model_dump_json()
    if isinstance(vista, list):
        return json.dumps([m.model_dump(mode="json") for m in vista], ensure_ascii=False)
    return json.dumps(vista, ensure_ascii=False)


def _texto_final(resp) -> str:
    texto = "".join(b.text for b in resp.content if b.type == "text").strip()
    return texto or FALLBACK
