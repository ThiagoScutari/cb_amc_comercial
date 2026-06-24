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
import unicodedata
from collections.abc import Iterable
from decimal import Decimal, InvalidOperation
from functools import lru_cache
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


# ── Equivalência de gênero de cor DERIVADA DO CATÁLOGO (fix S13b: "branca" x "Branco") ──
def _sem_acento(texto: str) -> str:
    """Remove acentos (NFD + descarta marcas de combinação)."""
    return "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    )


def _norm_cor(termo: str) -> str:
    """Normaliza um termo de cor p/ comparação: sem acento, casefold, sem bordas."""
    return _sem_acento(termo).casefold().strip()


def cores_do_catalogo(produtos: Iterable[Produto]) -> frozenset[str]:
    """PALAVRAS de cor reais (normalizadas) do catálogo — o conjunto-verdade p/ validar
    equivalências. Cores compostas ('Azul Darkness', 'Branco / Preto') são quebradas em
    palavras; a validação de gênero então funciona por palavra, sem heurística frágil.
    """
    palavras: set[str] = set()
    for p in produtos:
        if not p.cor:
            continue
        for tok in p.cor.replace("/", " ").split():
            n = _norm_cor(tok)
            if n:
                palavras.add(n)
    return frozenset(palavras)


@lru_cache(maxsize=1)
def cores_validas() -> frozenset[str]:
    """Conjunto de cores reais derivado do fixture (carregado UMA vez, determinístico)."""
    return cores_do_catalogo(carregar_produtos())


def _inverter_genero(termo_norm: str) -> str | None:
    """Inverte a vogal final -a<->-o de UMA palavra já normalizada. Outra terminação -> None."""
    if not termo_norm:
        return None
    if termo_norm[-1] == "a":
        return termo_norm[:-1] + "o"
    if termo_norm[-1] == "o":
        return termo_norm[:-1] + "a"
    return None


def equivalente_genero_cor(termo: str, cores: frozenset[str] | None = None) -> str | None:
    """Equivalência de gênero DERIVADA DO CATÁLOGO (anti "branca" x "Branco").

    Se `termo` NÃO é cor real mas seu inverso de gênero (vogal final -a<->-o) É uma cor
    real do catálogo, devolve o inverso NORMALIZADO; senão None. INVARIANTE: zero falso
    positivo — um inverso que não é cor real do catálogo casa NADA. Sem stemming/radical:
    só a inversão de gênero validada contra `cores` (default: as cores do fixture).
    """
    cores = cores if cores is not None else cores_validas()
    n = _norm_cor(termo)
    if not n or n in cores:
        return None  # vazio, ou já casa direto: nada a acrescentar
    inv = _inverter_genero(n)
    if inv is not None and inv in cores:
        return inv
    return None
