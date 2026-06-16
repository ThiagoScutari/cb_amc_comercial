#!/usr/bin/env python
"""Captura exploratória do catálogo Colcci via Firecrawl (scraping).

STANDALONE — vive em scripts/, fora de app/. NÃO é importado pelo app nem pelos
testes. Roda manualmente para popular tests/fixtures/colcci_products.json; os
testes e o seed leem SOMENTE o fixture, nunca chamam Firecrawl ao vivo.

Por que scraping e não a API VTEX: a API pública de catálogo da Colcci não expõe
os produtos (redireciona para a busca textual do storefront / 403 sem User-Agent),
então a fonte de verdade do catálogo passa a ser este fixture (revisão de Q8/§5.6).

Chave: lida de FIRECRAWL_API_KEY (variável de ambiente) ou de um .env local
(gitignored). NUNCA hardcode a chave aqui.

Uso:
    FIRECRAWL_API_KEY=... python scripts/capture_colcci.py
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.data.models import parse_ref_produto  # noqa: E402  (reuso do parser do modelo)

FIRECRAWL = "https://api.firecrawl.dev/v1"
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
SLEEP_S = 1.5  # cortesia: throttle entre chamadas
PER_GENERO_PRODUTOS = 14  # ~14 produtos × ~4 tamanhos × 2 gêneros ≈ ~110 SKUs
PER_LISTAGEM = 3  # cap por listagem -> espalha por categoria (paleta/cor mais ricas)
FIXTURE = ROOT / "tests" / "fixtures" / "colcci_products.json"

# Listagens reais (descobertas via Firecrawl /map). Só listagens COM gênero na URL
# — fonte confiável p/ o campo `genero` (NOT NULL). Variedade de categoria garante
# paleta de cores rica e mix de ref 9 díg. (tops) vs 8 díg. (bottoms/saia/bermuda).
# Acessórios (/acessorios/*) são omitidos: a URL não traz gênero e não inventamos.
LISTINGS: dict[str, list[str]] = {
    "Feminino": [
        "https://www.colcci.com.br/colcci-daily/feminino/camisetas-e-regatas",
        "https://www.colcci.com.br/feminino/vestido",
        "https://www.colcci.com.br/feminino/blazer",
        "https://www.colcci.com.br/feminino/saia",
        "https://www.colcci.com.br/feminino/jaqueta",
        "https://www.colcci.com.br/feminino/calca",
    ],
    "Masculino": [
        "https://www.colcci.com.br/colcci-daily/masculino/camisas-e-polos",
        "https://www.colcci.com.br/colcci-daily/masculino/bermudas-e-calcas",
        "https://www.colcci.com.br/colcci-daily/masculino/blusoes-e-jaquetas",
        "https://www.colcci.com.br/masculino/calca",
        "https://www.colcci.com.br/novidades/masculino/polo",
        "https://www.colcci.com.br/masculino/roupa/regata",
    ],
}

PROD_URL_RE = re.compile(r"-p\d+/?$")
REF_IN_URL_RE = re.compile(r"-(\d{6,10})-p\d+/?$")

PRODUTO_SCHEMA = {
    "type": "object",
    "properties": {
        "produto": {"type": "string"},
        "referencia": {"type": "string"},
        "cor": {"type": "string"},
        "tamanhos": {"type": "array", "items": {"type": "string"}},
        "preco": {"type": "string"},
        "genero": {"type": "string"},
    },
}
EXTRACT_PROMPT = (
    "Extraia os dados do produto desta página de e-commerce de moda. "
    "tamanhos = lista de tamanhos disponíveis para compra (ex.: PP, P, M, G, GG, "
    "ou numéricos). genero = Feminino ou Masculino. referencia = código/SKU do "
    "produto. preco = preço numérico (à vista), sem símbolo de moeda."
)


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def load_key() -> str:
    key = os.environ.get("FIRECRAWL_API_KEY")
    if not key:
        envp = ROOT / ".env"
        if envp.exists():
            for line in envp.read_text(encoding="utf-8").splitlines():
                if line.strip().startswith("FIRECRAWL_API_KEY"):
                    key = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    if not key:
        raise SystemExit("FIRECRAWL_API_KEY ausente (defina no env ou em .env).")
    return key.strip()


def fc_scrape(client: httpx.Client, url: str, body_extra: dict) -> dict:
    """POST /scrape com 2 tentativas e backoff. Retorna o dict `data` (ou {})."""
    body = {"url": url, "headers": {"User-Agent": BROWSER_UA}, **body_extra}
    for attempt in (1, 2):
        try:
            r = client.post(f"{FIRECRAWL}/scrape", json=body, timeout=180)
            if r.status_code == 200:
                return r.json().get("data", {}) or {}
            log(f"  [warn] {url} -> HTTP {r.status_code} (tentativa {attempt})")
        except httpx.HTTPError as e:  # degradação graciosa: não quebra a carga
            log(f"  [warn] {url} -> {e!r} (tentativa {attempt})")
        time.sleep(SLEEP_S * attempt)
    return {}


def coletar_urls_produto(client: httpx.Client, listagem: str, limite: int) -> list[str]:
    data = fc_scrape(client, listagem, {"formats": ["links"], "onlyMainContent": False})
    links = data.get("links", []) or []
    vistos: list[str] = []
    for raw in links:
        u = raw.split("?")[0]
        if PROD_URL_RE.search(u) and u not in vistos:
            vistos.append(u)
        if len(vistos) >= limite:
            break
    return vistos


def parse_preco(valor: str | None) -> str | None:
    if not valor:
        return None
    m = re.search(r"\d[\d.,]*", valor)
    if not m:
        return None
    s = m.group(0).replace(".", "").replace(",", ".") if "," in m.group(0) else m.group(0)
    try:
        return f"{float(s):.2f}"
    except ValueError:
        return None


def extrair_ref(detalhe: dict, url: str) -> str | None:
    ref = (detalhe.get("referencia") or "").strip()
    if ref.isdigit():
        return ref
    m = REF_IN_URL_RE.search(url)  # fallback: ref embutida na URL — NUNCA inventar
    return m.group(1) if m else (ref or None)


def normalizar(detalhe: dict, url: str, genero: str, categoria_txt: str) -> list[dict]:
    """Expande 1 produto (1 cor) em N linhas — uma por tamanho (1 linha = 1 SKU)."""
    ref = extrair_ref(detalhe, url)
    # âncora-direita (v1.8); ref malformado (<7 díg) -> (None, None, None), nunca inventa.
    tipo_cod, marca_cod, ordem = parse_ref_produto(ref)
    decodificado = tipo_cod is not None
    preco = parse_preco(detalhe.get("preco"))
    tamanhos = [t for t in (detalhe.get("tamanhos") or []) if t] or [None]
    rows = []
    for tam in tamanhos:
        rows.append(
            {
                "sku": f"{ref}-{tam}" if (ref and tam) else None,
                "ref_produto": ref,
                "tipo_cod": tipo_cod,
                "marca_cod": marca_cod,
                "ordem": ordem,
                "produto": detalhe.get("produto"),
                "tamanho": tam,
                "cor": detalhe.get("cor"),
                "preco_tabela": preco,
                # metadados (fora do modelo Produto) — só p/ transparência da captura:
                "_genero": detalhe.get("genero") or genero,
                "_categoria_txt": categoria_txt,
                "_ref_decodificado": decodificado,
                "_source_url": url,
            }
        )
    return rows


def categoria_da_url(listagem: str) -> str:
    return listagem.rstrip("/").split("/")[-1]


def main() -> None:
    key = load_key()
    headers = {"Authorization": f"Bearer {key}"}
    skus: list[dict] = []
    produtos_vistos: set[str] = set()

    with httpx.Client(headers=headers) as client:
        for genero, listagens in LISTINGS.items():
            alvo = PER_GENERO_PRODUTOS
            urls_produto: list[tuple[str, str]] = []  # (url, categoria_txt)
            for listagem in listagens:
                if len(urls_produto) >= alvo:
                    break
                faltam = min(alvo - len(urls_produto), PER_LISTAGEM)
                log(f"[{genero}] listagem {listagem}")
                for u in coletar_urls_produto(client, listagem, faltam):
                    if u not in produtos_vistos:
                        produtos_vistos.add(u)
                        urls_produto.append((u, categoria_da_url(listagem)))
                    if len(urls_produto) >= alvo:
                        break
                time.sleep(SLEEP_S)

            log(f"[{genero}] {len(urls_produto)} produtos a capturar")
            for url, categoria_txt in urls_produto:
                detalhe = fc_scrape(
                    client,
                    url,
                    {
                        "formats": ["json"],
                        "jsonOptions": {"schema": PRODUTO_SCHEMA, "prompt": EXTRACT_PROMPT},
                        "onlyMainContent": True,
                    },
                ).get("json", {})
                if not detalhe:
                    log(f"  [skip] sem dados: {url}")
                    continue
                novas = normalizar(detalhe, url, genero, categoria_txt)
                skus.extend(novas)
                log(
                    f"  [ok] {detalhe.get('produto')!r} ref={extrair_ref(detalhe, url)} "
                    f"-> {len(novas)} SKU(s)"
                )
                time.sleep(SLEEP_S)

    _salvar(skus)


def _salvar(skus: list[dict]) -> None:
    decodificados = sum(1 for s in skus if s["_ref_decodificado"])
    produtos = {s["_source_url"] for s in skus}
    meta = {
        "fonte": "scraping colcci.com.br via Firecrawl (API VTEX pública não expõe catálogo)",
        "total_skus": len(skus),
        "total_produtos": len(produtos),
        "skus_derivados_preenchidos": decodificados,
        "skus_malformados": len(skus) - decodificados,
        "sem_preco": sum(1 for s in skus if not s["preco_tabela"]),
        "sem_cor": sum(1 for s in skus if not s["cor"]),
        "sem_tamanho": sum(1 for s in skus if not s["tamanho"]),
    }
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(
        json.dumps({"_meta": meta, "skus": skus}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log("\n=== RESUMO ===")
    for k, v in meta.items():
        log(f"{k}: {v}")
    log(f"fixture: {FIXTURE}")


if __name__ == "__main__":
    main()
