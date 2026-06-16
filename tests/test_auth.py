"""Testes da auth/sessão (telefone -> cliente_id) com política fail-closed.

SQLite + seed (auth é lógica; o IDOR de fidelidade já está na Fase 2).
"""

import pytest
from app.agent.tools import Ferramentas, PedidoView
from app.auth.session import (
    MotivoNegacao,
    SessaoAutenticada,
    SessaoNegada,
    cliente_id_de,
    resolver_sessao,
)
from app.data.models import Cliente
from app.data.repository import MockRepository
from app.data.seed import popular
from sqlalchemy.exc import MultipleResultsFound


@pytest.fixture
def repo(session) -> MockRepository:
    popular(session)
    session.flush()
    return MockRepository(session)


class _RepoAmbiguo:
    """Stub: modela o ERP sem unique de telefone (>1 cliente p/ o mesmo número)."""

    def cliente_por_telefone(self, telefone: str):
        raise MultipleResultsFound("dois clientes com o mesmo telefone")


# ---------- conhecido ----------
def test_telefone_conhecido_autentica(repo):
    s = resolver_sessao("5531999990001", repo)
    assert isinstance(s, SessaoAutenticada)
    assert s.cliente_id == 1
    assert s.nome  # nome_fantasia preenchido


def test_variacao_de_telefone_autentica_mesmo_cliente(repo):
    for variacao in ("+55 31 99999-0001", "31999990001", "553199990001"):
        s = resolver_sessao(variacao, repo)
        assert isinstance(s, SessaoAutenticada)
        assert s.cliente_id == 1


def test_autenticado_constroi_ferramentas_e_le_proprio(repo):
    s = resolver_sessao("5531999990001", repo)
    cid = cliente_id_de(s)
    assert cid == 1
    ferramentas = Ferramentas(repo, cliente_id=cid)
    assert isinstance(ferramentas.consultar_pedido(4471), PedidoView)


# ---------- desconhecido / lixo ----------
def test_desconhecido_nega_e_escala(repo):
    s = resolver_sessao("5531900000099", repo)  # válido, mas fora do seed
    assert isinstance(s, SessaoNegada)
    assert s.motivo == MotivoNegacao.numero_desconhecido
    assert s.escalar is True
    assert s.mensagem


def test_telefone_lixo_ou_vazio_nega(repo):
    for ruim in ("", None, "abc", "123"):
        s = resolver_sessao(ruim, repo)
        assert isinstance(s, SessaoNegada)


def test_telefone_normaliza_para_vazio_nega(repo):
    # só pontuação/sinais -> normaliza para None -> negado (não casa com ninguém)
    s = resolver_sessao("++ () --", repo)
    assert isinstance(s, SessaoNegada)
    assert s.motivo == MotivoNegacao.numero_desconhecido


# ---------- inativo ----------
def test_cliente_inativo_politica(repo):
    repo.session.add(
        Cliente(
            razao_social="Inativa LTDA",
            nome_fantasia="Inativa",
            cnpj="00000000000099",
            telefone_whatsapp="5531900000088",
            contato_nome="Z",
            cidade_uf="BH/MG",
            condicao_pagamento="à vista",
            ativo=False,
        )
    )
    repo.session.flush()
    s = resolver_sessao("5531900000088", repo)
    assert isinstance(s, SessaoNegada)
    assert s.motivo == MotivoNegacao.cliente_inativo
    assert s.escalar is True


# ---------- fail-closed 🔒 ----------
def test_fail_closed_negada_nao_da_cliente_id(repo):
    s = resolver_sessao("abc", repo)
    assert isinstance(s, SessaoNegada)
    assert cliente_id_de(s) is None
    assert not hasattr(s, "cliente_id")  # o tipo não oferece o valor


def test_fail_closed_caminho_negado_nao_instancia_ferramentas(repo):
    s = resolver_sessao("5531900000099", repo)  # desconhecido
    cid = cliente_id_de(s)
    assert cid is None
    ferramentas = Ferramentas(repo, cid) if cid is not None else None
    assert ferramentas is None  # ramo de dados não roda no caminho negado


def test_fail_closed_numero_ambiguo_nega():
    # >1 cliente p/ o número -> negar, SEM exceção, sem autenticar nenhum dos dois.
    s = resolver_sessao("5531999990001", _RepoAmbiguo())
    assert isinstance(s, SessaoNegada)
    assert s.escalar is True
    assert s.motivo == MotivoNegacao.cadastro_ambiguo
    assert cliente_id_de(s) is None
