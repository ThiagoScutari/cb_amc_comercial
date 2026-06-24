"""Testes do seed (coerência, demo, idempotência). SQLite in-memory, sem rede."""

from collections import defaultdict
from decimal import Decimal

import pytest
from app.data.catalogo import carregar_produtos
from app.data.db import criar_engine, recriar_schema
from app.data.models import (
    STATUS_FATURADOS,
    Cliente,
    Devolucao,
    Estoque,
    NotaFiscal,
    Pedido,
    PedidoItem,
    Produto,
    Solicitacao,
    StatusDevolucao,
    StatusEntrega,
    StatusPedido,
    StatusSolicitacao,
    StatusTitulo,
    Titulo,
)
from app.data.seed import DATA_REF, DEMO_CLIENTE_ID, popular
from sqlalchemy import select
from sqlalchemy.orm import Session


@pytest.fixture
def db(session) -> Session:
    popular(session)
    session.flush()
    return session


# ---------- contagens ----------
def test_contagens(db):
    assert len(db.scalars(select(Cliente)).all()) == 3  # roster enxuto {1, 2, 3} (S17a)
    assert len(db.scalars(select(Produto)).all()) == len(carregar_produtos())
    assert len(db.scalars(select(Pedido)).all()) >= 9


# ---------- valor_total = soma dos itens ----------
def test_valor_total_soma_dos_itens(db):
    itens_por_pedido: dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
    for it in db.scalars(select(PedidoItem)).all():
        itens_por_pedido[it.pedido_id] += it.quantidade * it.preco_unitario
    for ped in db.scalars(select(Pedido)).all():
        assert ped.valor_total == itens_por_pedido[ped.id]


# ---------- estoque coerente com Q2 ----------
def test_estoque_coerente_reservado_disponivel(db):
    ped_by_id = {p.id: p for p in db.scalars(select(Pedido)).all()}
    res: dict[int, int] = defaultdict(int)
    disp: dict[int, int] = defaultdict(int)
    for it in db.scalars(select(PedidoItem)).all():
        st = ped_by_id[it.pedido_id].status
        if st in STATUS_FATURADOS:
            res[it.sku_id] += it.quantidade
        elif st != StatusPedido.cancelado:  # não-faturado e não-cancelado
            disp[it.sku_id] += it.quantidade
    for e in db.scalars(select(Estoque)).all():
        assert e.reservado == res[e.sku_id]
        assert e.disponivel == disp[e.sku_id]
        assert e.saldo >= 0 and e.disponivel >= 0 and e.reservado >= 0


def test_cancelado_nao_conta_no_estoque(db):
    cancelados = {
        p.id for p in db.scalars(select(Pedido)).all() if p.status == StatusPedido.cancelado
    }
    qtd_cancelada = sum(
        it.quantidade for it in db.scalars(select(PedidoItem)).all() if it.pedido_id in cancelados
    )
    qtd_nao_cancelada = sum(
        it.quantidade
        for it in db.scalars(select(PedidoItem)).all()
        if it.pedido_id not in cancelados
    )
    total_comprometido = sum(e.reservado + e.disponivel for e in db.scalars(select(Estoque)).all())
    assert qtd_cancelada > 0  # há ao menos um pedido cancelado (caso faturado->cancelado)
    assert total_comprometido == qtd_nao_cancelada  # itens cancelados NÃO entram


# ---------- integridade referencial ----------
def test_integridade_referencial(db):
    cli_ids = {c.id for c in db.scalars(select(Cliente)).all()}
    prod_ids = {p.id for p in db.scalars(select(Produto)).all()}
    ped_ids = {p.id for p in db.scalars(select(Pedido)).all()}
    for p in db.scalars(select(Pedido)).all():
        assert p.cliente_id in cli_ids
    for it in db.scalars(select(PedidoItem)).all():
        assert it.pedido_id in ped_ids
        assert it.sku_id in prod_ids
    for s in db.scalars(select(Solicitacao)).all():
        assert s.cliente_id in cli_ids


# ---------- demo: §10 ----------
def test_pedido_4471_existe_e_cancelavel(db):
    p = db.get(Pedido, 4471)
    assert p is not None
    assert p.cliente_id == DEMO_CLIENTE_ID
    assert p.faturado is False  # não-faturado -> cancelável ("quero cancelar o 4471")
    assert len(p.itens) >= 1


def test_camiseta_demo_e_compravel(db):
    prod = db.scalars(select(Produto).where(Produto.sku == "340103413-M")).one()
    est = db.get(Estoque, prod.id)
    assert est.saldo > 0  # "tem camiseta ... M pra comprar?" -> saldo>0


# ---------- S17b: grade realista (5–10 SKUs por pedido) ----------
def test_pedidos_tem_grade_realista_5_a_10_skus_distintos(db):
    for p in db.scalars(select(Pedido)).all():
        skus = [it.sku_id for it in p.itens]
        assert 5 <= len(skus) <= 10, (p.id, len(skus))  # engorda
        assert len(skus) == len(set(skus)), f"SKU repetido no pedido {p.id}"


def test_pedido_4471_engordado_mantem_a_camiseta_ancora(db):
    p = db.get(Pedido, 4471)
    skus = {it.sku.sku for it in p.itens}
    assert "340103413-M" in skus  # âncora (camiseta branca M) preservada na grade
    assert 5 <= len(p.itens) <= 10


def test_todos_os_status_cobertos_no_cliente_demo(db):
    status = {
        p.status
        for p in db.scalars(select(Pedido).where(Pedido.cliente_id == DEMO_CLIENTE_ID)).all()
    }
    assert status == set(StatusPedido)


def test_solicitacao_pendente_pertence_ao_cliente(db):
    sols = [
        s for s in db.scalars(select(Solicitacao)).all() if s.status == StatusSolicitacao.pendente
    ]
    assert len(sols) >= 1
    for s in sols:
        if s.pedido_id is not None:  # anti-IDOR no caminho de escrita (contrato Fase 5)
            assert db.get(Pedido, s.pedido_id).cliente_id == s.cliente_id


def test_distribuicao_de_saldo_para_demo(db):
    saldos = [e.saldo for e in db.scalars(select(Estoque)).all()]
    assert any(s == 0 for s in saldos)  # sold-out
    assert any(0 < s <= 3 for s in saldos)  # estoque baixo (urgência)
    assert any(s >= 15 for s in saldos)  # confortável


def test_condicao_pagamento_preenchida(db):
    for c in db.scalars(select(Cliente)).all():
        assert c.condicao_pagamento  # "qual minha condição de pagamento?"


# ---------- sanidade gênero x tipo_cod ----------
def test_genero_coerente_com_tipo_cod(db):
    # tipo_cod codifica peça+gênero: último dígito ímpar=Masculino, par=Feminino.
    for p in db.scalars(select(Produto)).all():
        if p.tipo_cod is None:
            continue
        esperado_masc = int(p.tipo_cod) % 2 == 1
        assert (p.genero == "Masculino") == esperado_masc


# ---------- idempotência / determinismo ----------
def test_determinismo_entre_execucoes():
    resultados = []
    for _ in range(2):
        eng = criar_engine("sqlite://")
        recriar_schema(eng)
        with Session(eng) as s:
            popular(s)
            s.commit()
            resultados.append(
                (
                    len(s.scalars(select(Cliente)).all()),
                    len(s.scalars(select(Pedido)).all()),
                    s.get(Pedido, 4471).valor_total,
                )
            )
        eng.dispose()
    assert resultados[0] == resultados[1]


# ---------- db.py ----------
def test_recriar_schema_em_sqlite():
    eng = criar_engine("sqlite://")
    recriar_schema(eng)
    with Session(eng) as s:
        s.add(
            Cliente(
                razao_social="X LTDA",
                nome_fantasia="X",
                cnpj="00000000000000",
                telefone_whatsapp="550000",
                contato_nome="Y",
                cidade_uf="BH/MG",
                condicao_pagamento="à vista",
            )
        )
        s.commit()
        assert len(s.scalars(select(Cliente)).all()) == 1
    eng.dispose()


# ---------- S12: entidades fiscais (NF / título / devolução) ----------
def test_nf_uma_por_pedido_faturado_do_demo(db):
    nfs = db.scalars(select(NotaFiscal).where(NotaFiscal.cliente_id == DEMO_CLIENTE_ID)).all()
    assert {n.numero_nf for n in nfs} == {60001, 60002, 60003, 60004, 60005}
    assert {n.pedido_id for n in nfs} == {4473, 4474, 4475, 4476, 4477}
    for n in nfs:  # toda NF amarrada a um pedido FATURADO
        assert db.get(Pedido, n.pedido_id).status in STATUS_FATURADOS


def test_nf_valor_igual_ao_pedido_e_chave_44(db):
    for n in db.scalars(select(NotaFiscal)).all():
        assert n.valor_total == db.get(Pedido, n.pedido_id).valor_total  # invariante
        assert len(n.chave_acesso) == 44 and n.chave_acesso.isdigit()


def test_nf_status_entrega_coerente_com_pedido(db):
    esperado = {
        4473: StatusEntrega.emitida,
        4474: StatusEntrega.coletada,
        4475: StatusEntrega.em_transito,
        4476: StatusEntrega.em_transito,
        4477: StatusEntrega.entregue,
    }
    nf_by_ped = {n.pedido_id: n for n in db.scalars(select(NotaFiscal)).all()}
    for ped, st in esperado.items():
        assert nf_by_ped[ped].status_entrega == st
    assert nf_by_ped[4477].data_entrega is not None  # entregue -> data_entrega
    assert nf_by_ped[4475].codigo_rastreio  # em_transito -> rastreio + prevista
    assert nf_by_ped[4475].data_prevista_entrega is not None


def test_titulos_somam_valor_da_nf(db):
    # INVARIANTE: Σ parcelas == valor_total da NF (a última parcela absorve o centavo).
    por_nf: dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
    for t in db.scalars(select(Titulo)).all():
        por_nf[t.nota_fiscal_id] += t.valor
    for nf in db.scalars(select(NotaFiscal)).all():
        assert por_nf[nf.id] == nf.valor_total


def test_titulos_referenciam_nf_existente(db):
    nf_ids = {n.id for n in db.scalars(select(NotaFiscal)).all()}
    titulos = db.scalars(select(Titulo)).all()
    assert titulos
    for t in titulos:
        assert t.nota_fiscal_id in nf_ids


def test_titulos_demo_3_parcelas_e_uma_paga(db):
    nf1 = db.scalars(select(NotaFiscal).where(NotaFiscal.numero_nf == 60001)).one()
    parcelas = db.scalars(select(Titulo).where(Titulo.nota_fiscal_id == nf1.id)).all()
    assert len(parcelas) == 3  # cliente 1 = "28/35/42 dias"
    pagos = [t for t in parcelas if t.status == StatusTitulo.pago]
    assert len(pagos) == 1 and pagos[0].data_pagamento is not None


def test_titulo_vencido_tem_vencimento_passado_sem_pagamento(db):
    vencidos = db.scalars(select(Titulo).where(Titulo.status == StatusTitulo.vencido)).all()
    assert vencidos  # ao menos um (NF do pedido entregue, o mais antigo)
    for t in vencidos:
        assert t.data_vencimento < DATA_REF
        assert t.data_pagamento is None


def test_devolucoes_cobrem_os_tres_estados_alvo(db):
    status = {
        d.status
        for d in db.scalars(select(Devolucao).where(Devolucao.cliente_id == DEMO_CLIENTE_ID)).all()
    }
    assert {
        StatusDevolucao.aguardando_postagem,
        StatusDevolucao.prazo_postagem_expirado,
        StatusDevolucao.credito_gerado,
    } <= status


def test_devolucoes_coerencia_temporal_e_credito(db):
    devs = {d.numero_devolucao: d for d in db.scalars(select(Devolucao)).all()}
    # aguardando_postagem: tem código e prazo FUTURO
    ag = devs["80001"]
    assert ag.status == StatusDevolucao.aguardando_postagem
    assert ag.codigo_postagem and ag.prazo_postagem > DATA_REF
    # prazo expirado: prazo PASSADO e sem código novo (a dor do comercial)
    ex = devs["80002"]
    assert ex.status == StatusDevolucao.prazo_postagem_expirado
    assert ex.prazo_postagem < DATA_REF and ex.codigo_postagem is None
    # crédito gerado: devolução TOTAL -> valor_credito == valor_total da NF amarrada (>= 0)
    cr = devs["80003"]
    nf_cr = db.scalars(select(NotaFiscal).where(NotaFiscal.numero_nf == 60005)).one()
    assert cr.valor_credito == nf_cr.valor_total  # crédito integral
    assert cr.valor_credito >= 0  # CHECK do schema
    assert cr.data_credito is not None


def test_cross_client_tem_entidades_fiscais(db):
    # cliente != 1 com NF + título + devolução -> alvo do IDOR cross-client (S13)
    outro = 2
    assert db.scalars(select(NotaFiscal).where(NotaFiscal.cliente_id == outro)).all()
    assert db.scalars(select(Titulo).where(Titulo.cliente_id == outro)).all()
    assert db.scalars(select(Devolucao).where(Devolucao.cliente_id == outro)).all()


def test_determinismo_fiscais_entre_execucoes():
    snaps = []
    for _ in range(2):
        eng = criar_engine("sqlite://")
        recriar_schema(eng)
        with Session(eng) as s:
            popular(s)
            s.commit()
            snaps.append(
                (
                    len(s.scalars(select(NotaFiscal)).all()),
                    len(s.scalars(select(Titulo)).all()),
                    len(s.scalars(select(Devolucao)).all()),
                    s.scalars(select(NotaFiscal).where(NotaFiscal.numero_nf == 60001))
                    .one()
                    .valor_total,
                    sorted(t.numero_titulo for t in s.scalars(select(Titulo)).all()),
                    sorted(
                        (d.numero_devolucao, str(d.status))
                        for d in s.scalars(select(Devolucao)).all()
                    ),
                )
            )
        eng.dispose()
    assert snaps[0] == snaps[1]
