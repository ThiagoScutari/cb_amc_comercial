"""Loader do catálogo Colcci: fixture JSON -> list[Produto]. SEM REDE.

Código de produção. Lê o snapshot congelado em app/data/colcci_products.json
(fonte de verdade da demo, §5.6) e constrói objetos `Produto`. NUNCA chama Firecrawl
— a captura ao vivo vive em scripts/capture_colcci.py, rodada sob demanda.

O snapshot vive em app/data/ (não em tests/) porque é dado de PRODUÇÃO consumido
em runtime pelo seed: assim ele entra na imagem Docker via `COPY app/`.

Reusa `parse_ref_produto` (models.py): deriva categoria_cod/marca_cod/ordem só quando
o ref tem 9 dígitos; para 8 dígitos, deixa null (degrada, nunca inventa — §5.2).
O seed (Fase 1c) consome `carregar_produtos` para popular a tabela `produtos`.
"""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from pathlib import Path

from app.data.models import Produto, parse_ref_produto

FIXTURE_PADRAO = Path(__file__).resolve().parent / "colcci_products.json"


def _preco_para_decimal(valor: str | None) -> Decimal | None:
    if valor is None:
        return None
    try:
        return Decimal(str(valor))
    except (InvalidOperation, ValueError):  # degrada: preço inválido não quebra a carga
        return None


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
        # âncora-direita; ref malformado -> (None, None, None), nunca inventa.
        tipo_cod, marca_cod, ordem = parse_ref_produto(ref)
        produtos.append(
            Produto(
                sku=sku,
                ref_produto=ref,
                tipo_cod=tipo_cod,
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
