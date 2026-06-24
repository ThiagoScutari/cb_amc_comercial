"""Testes do loader do catálogo (app/data/catalogo.py).

Lê SOMENTE o fixture congelado (app/data/colcci_products.json); nunca chama
Firecrawl. Casos de borda usam fixtures temporários (tmp_path).
"""

import json
from decimal import Decimal

from app.data.catalogo import (
    carregar_produtos,
    cores_do_catalogo,
    cores_validas,
    equivalente_genero_cor,
)
from app.data.models import Produto, parse_ref_produto
from sqlalchemy import select


def test_carrega_produtos_do_fixture():
    produtos = carregar_produtos()
    assert len(produtos) > 50
    skus = [p.sku for p in produtos]
    assert len(skus) == len(set(skus))  # sku único (dedup)
    assert all(p.genero in {"Feminino", "Masculino"} for p in produtos)
    assert all(p.categoria_txt for p in produtos)


def test_derivados_via_ancora_direita():
    produtos = carregar_produtos()
    # Todo produto deve ter derivados coerentes com o parser (âncora-direita).
    for p in produtos:
        assert (p.tipo_cod, p.marca_cod, p.ordem) == parse_ref_produto(p.ref_produto)
    # Com a v1.8, ref de 8 díg. AGORA preenche (não é mais null).
    p8 = next(p for p in produtos if p.ref_produto and len(p.ref_produto) == 8)
    assert p8.tipo_cod is not None
    assert p8.ordem is not None
    assert p8.marca_cod == "01"  # Colcci


def test_preco_vira_decimal():
    produtos = carregar_produtos()
    p = next(p for p in produtos if p.preco_tabela is not None)
    assert isinstance(p.preco_tabela, Decimal)


def test_loader_casos_de_borda(tmp_path):
    fx = tmp_path / "f.json"
    fx.write_text(
        json.dumps(
            {
                "skus": [
                    {
                        "sku": "X-1",
                        "ref_produto": "340103413",
                        "produto": "Camiseta",
                        "tamanho": "M",
                        "cor": "Azul",
                        "preco_tabela": "10.00",
                        "_genero": "Feminino",
                        "_categoria_txt": "camisetas-e-regatas",
                    },
                    {  # duplicata de sku -> deduplicada
                        "sku": "X-1",
                        "ref_produto": "340103413",
                        "produto": "Camiseta",
                        "tamanho": "M",
                        "cor": "Azul",
                        "preco_tabela": "10.00",
                        "_genero": "Feminino",
                        "_categoria_txt": "camisetas-e-regatas",
                    },
                    {  # sem sku -> descartada
                        "sku": None,
                        "ref_produto": "340103999",
                        "_genero": "Feminino",
                    },
                    {  # ref 8 díg. (decodifica) + preço inválido
                        "sku": "Y-1",
                        "ref_produto": "80104766",
                        "produto": "Saia",
                        "tamanho": "P",
                        "cor": "Preto",
                        "preco_tabela": "n/d",
                        "_genero": "Feminino",
                        "_categoria_txt": "calcas-e-saias",
                    },
                    {  # ref malformado (<7 díg) -> derivados null
                        "sku": "Z-1",
                        "ref_produto": "12",
                        "produto": "Malformado",
                        "tamanho": "U",
                        "cor": "Cru",
                        "preco_tabela": "5.00",
                        "_genero": "Feminino",
                        "_categoria_txt": "outros",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    produtos = carregar_produtos(fx)
    assert [p.sku for p in produtos] == ["X-1", "Y-1", "Z-1"]
    y = next(p for p in produtos if p.sku == "Y-1")
    assert y.tipo_cod == "008"  # 80104766 = tipo 008 . marca 01 . ordem 04766
    assert y.preco_tabela is None  # preço inválido vira None (não quebra)
    z = next(p for p in produtos if p.sku == "Z-1")
    assert z.tipo_cod is None  # ref malformado: derivados null (nunca inventa)


def test_produtos_persistem_no_banco(session):
    # genero NOT NULL satisfeito -> persiste sem IntegrityError.
    produtos = carregar_produtos()
    session.add_all(produtos[:20])
    session.commit()
    assert len(session.scalars(select(Produto)).all()) == 20


# --------- S13b: equivalência de gênero de cor (derivada do fixture) ---------
def test_cores_validas_normaliza_e_quebra_compostas():
    cores = cores_validas()
    assert {"branco", "preto", "azul", "cinza"} <= cores
    assert "darkness" in cores  # de "Azul Darkness" — composta quebrada em palavras
    assert "indigo" in cores  # "Índigo" normalizado SEM acento
    assert all(c == c.casefold() for c in cores)  # tudo normalizado


def test_cores_do_catalogo_e_funcao_pura():
    # opera sobre qualquer lista de produtos; compostas/`/`/acento -> palavras normalizadas.
    ps = [Produto(cor="Branco / Preto"), Produto(cor="Índigo"), Produto(cor=None)]
    assert cores_do_catalogo(ps) == {"branco", "preto", "indigo"}


def test_equivalente_genero_branca_para_branco():
    assert equivalente_genero_cor("branca") == "branco"
    assert equivalente_genero_cor("Branca") == "branco"  # case/acento-insensível
    assert equivalente_genero_cor("preta") == "preto"


def test_equivalente_cor_real_direta_nao_inverte():
    # já é cor real do catálogo: não precisa de equivalência -> None
    assert equivalente_genero_cor("branco") is None
    assert equivalente_genero_cor("cinza") is None  # termina em 'a' mas É cor real


def test_equivalente_zero_falso_positivo():
    # inverso que NÃO é cor real do catálogo -> None (sem stemming, sem chute)
    assert equivalente_genero_cor("marinha") is None  # 'marinho' não existe no fixture
    assert equivalente_genero_cor("rosa") is None  # 'roso' não existe
    assert equivalente_genero_cor("bege") is None  # termina em 'e' (não a/o)
    assert equivalente_genero_cor("") is None
