"""Testes do loader do catálogo (app/data/catalogo.py).

Lê SOMENTE o fixture congelado (tests/fixtures/colcci_products.json); nunca chama
Firecrawl. Casos de borda usam fixtures temporários (tmp_path).
"""

import json
from decimal import Decimal

from app.data.catalogo import carregar_produtos
from app.data.models import Produto, parse_ref_produto
from sqlalchemy import select


def test_carrega_produtos_do_fixture():
    produtos = carregar_produtos()
    assert len(produtos) > 50
    skus = [p.sku for p in produtos]
    assert len(skus) == len(set(skus))  # sku único (dedup)
    assert all(p.genero in {"Feminino", "Masculino"} for p in produtos)
    assert all(p.categoria_txt for p in produtos)


def test_ref9_parseado_e_ref8_nulo():
    produtos = carregar_produtos()
    ref9 = next(p for p in produtos if p.ref_produto and len(p.ref_produto) == 9)
    esperado = parse_ref_produto(ref9.ref_produto)
    assert (ref9.categoria_cod, ref9.marca_cod, ref9.ordem) == esperado
    assert ref9.marca_cod == "01"  # Colcci

    ref8 = next(p for p in produtos if p.ref_produto and len(p.ref_produto) == 8)
    assert ref8.categoria_cod is None
    assert ref8.marca_cod is None
    assert ref8.ordem is None


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
                    {  # ref 8 díg. + preço inválido
                        "sku": "Y-1",
                        "ref_produto": "80104766",
                        "produto": "Saia",
                        "tamanho": "P",
                        "cor": "Preto",
                        "preco_tabela": "n/d",
                        "_genero": "Feminino",
                        "_categoria_txt": "calcas-e-saias",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    produtos = carregar_produtos(fx)
    assert [p.sku for p in produtos] == ["X-1", "Y-1"]
    y = next(p for p in produtos if p.sku == "Y-1")
    assert y.categoria_cod is None  # ref de 8 díg.
    assert y.preco_tabela is None  # preço inválido vira None (não quebra)


def test_produtos_persistem_no_banco(session):
    # genero NOT NULL satisfeito -> persiste sem IntegrityError.
    produtos = carregar_produtos()
    session.add_all(produtos[:20])
    session.commit()
    assert len(session.scalars(select(Produto)).all()) == 20
