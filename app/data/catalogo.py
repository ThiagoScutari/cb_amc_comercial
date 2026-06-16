"""Loader do catálogo Colcci: fixture JSON -> list[Produto]. SEM REDE.

Código de produção. Lê o snapshot congelado em tests/fixtures/colcci_products.json
(fonte de verdade da demo, §5.6) e constrói objetos `Produto`. NUNCA chama Firecrawl
— a captura ao vivo vive em scripts/capture_colcci.py, rodada sob demanda.

Reusa `parse_ref_produto` (models.py): deriva categoria_cod/marca_cod/ordem só quando
o ref tem 9 dígitos; para 8 dígitos, deixa null (degrada, nunca inventa — §5.2).
O seed (Fase 1c) consome `carregar_produtos` para popular a tabela `produtos`.
"""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from pathlib import Path

from app.data.models import Produto, parse_ref_produto

FIXTURE_PADRAO = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "colcci_products.json"


def _preco_para_decimal(valor: str | None) -> Decimal | None:
    if valor is None:
        return None
    try:
        return Decimal(str(valor))
    except (InvalidOperation, ValueError):  # degrada: preço inválido não quebra a carga
        return None


def _derivar_do_ref(ref: str | None) -> tuple[str | None, str | None, str | None]:
    if ref and len(ref) == 9 and ref.isdigit():
        return parse_ref_produto(ref)
    return None, None, None  # 8 díg. (ou ausente): null, nunca inventa


def carregar_produtos(fixture_path: str | Path = FIXTURE_PADRAO) -> list[Produto]:
    """Lê o fixture e devolve `Produto`s, deduplicados por `sku`. Não toca em rede."""
    data = json.loads(Path(fixture_path).read_text(encoding="utf-8"))
    vistos: set[str] = set()
    produtos: list[Produto] = []
    for row in data.get("skus", []):
        sku = row.get("sku")
        if not sku or sku in vistos:  # descarta sku ausente; deduplica
            continue
        vistos.add(sku)
        ref = row.get("ref_produto")
        categoria_cod, marca_cod, ordem = _derivar_do_ref(ref)
        produtos.append(
            Produto(
                sku=sku,
                ref_produto=ref,
                categoria_cod=categoria_cod,
                marca_cod=marca_cod,
                ordem=ordem,
                genero=row.get("_genero"),
                categoria_txt=row.get("_categoria_txt"),
                produto=row.get("produto"),
                tamanho=row.get("tamanho"),
                cor=row.get("cor"),
                preco_tabela=_preco_para_decimal(row.get("preco_tabela")),
            )
        )
    return produtos
