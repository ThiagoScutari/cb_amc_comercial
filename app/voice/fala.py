"""Conversor texto-formatado -> texto-falável (números/datas por extenso). SEM REDE.

Roda no dispatcher ENTRE `responder()` e `sintetizar()` (router.py): o agente gera
UMA resposta formatada (dígitos, R$ 0.000,00, dd/mm/aaaa) para o TEXTO; aqui ela é
convertida para fala ANTES do TTS. O conteúdo é o MESMO — só a forma muda — então a
porta única é preservada (o áudio é derivado do texto, sem geração paralela).

ESCOPO (do nosso domínio, não o universo): inteiros até ~milhares, valores em reais
(reais/centavos, "um real" singular), datas dd/mm/aaaa (ano em dígitos), RefId de 7+
dígitos lido dígito a dígito, e ano 1900-2099 solto preservado em dígitos.

SEGURO (inviolável): `para_fala` degrada para o texto ORIGINAL em QUALQUER erro. O
áudio NUNCA pode quebrar por causa da conversão — no pior caso, fala o texto formatado.
"""

from __future__ import annotations

import re

# --- léxico do português ---
_UNIDADES = {
    0: "zero", 1: "um", 2: "dois", 3: "três", 4: "quatro", 5: "cinco", 6: "seis",
    7: "sete", 8: "oito", 9: "nove", 10: "dez", 11: "onze", 12: "doze", 13: "treze",
    14: "catorze", 15: "quinze", 16: "dezesseis", 17: "dezessete", 18: "dezoito",
    19: "dezenove",
}  # fmt: skip
_DEZENAS = {
    2: "vinte", 3: "trinta", 4: "quarenta", 5: "cinquenta", 6: "sessenta",
    7: "setenta", 8: "oitenta", 9: "noventa",
}  # fmt: skip
_CENTENAS = {
    1: "cento", 2: "duzentos", 3: "trezentos", 4: "quatrocentos", 5: "quinhentos",
    6: "seiscentos", 7: "setecentos", 8: "oitocentos", 9: "novecentos",
}  # fmt: skip
_CENTENAS_FEM = {c: w[:-2] + "as" if c >= 2 else w for c, w in _CENTENAS.items()}
_DIGITO = {str(d): _UNIDADES[d] for d in range(10)}
_MESES = {
    1: "janeiro", 2: "fevereiro", 3: "março", 4: "abril", 5: "maio", 6: "junho",
    7: "julho", 8: "agosto", 9: "setembro", 10: "outubro", 11: "novembro", 12: "dezembro",
}  # fmt: skip

# Lista CURADA (revisável) de substantivos do domínio que pedem número no feminino.
# Inclui singular e plural; default é masculino quando o substantivo não está aqui.
_SUBST_FEMININOS = frozenset(
    {"peça", "peças", "unidade", "unidades", "caixa", "caixas", "dúzia", "dúzias"}
)


def _unidade(u: int, fem: bool) -> str:
    if fem and u == 1:
        return "uma"
    if fem and u == 2:
        return "duas"
    return _UNIDADES[u]


def _dezena(n: int, fem: bool) -> str:
    """1..99 por extenso."""
    if n < 20:
        return _unidade(n, fem)
    d, u = divmod(n, 10)
    return _DEZENAS[d] if u == 0 else f"{_DEZENAS[d]} e {_unidade(u, fem)}"


def _grupo(n: int, fem: bool) -> str:
    """1..999 por extenso (100 exato = 'cem'; 101.. = 'cento e ...')."""
    c, r = divmod(n, 100)
    if c == 0:
        return _dezena(r, fem)
    centena = "cem" if (c == 1 and r == 0) else ("cento" if c == 1 else _centena(c, fem))
    return centena if r == 0 else f"{centena} e {_dezena(r, fem)}"


def _centena(c: int, fem: bool) -> str:
    return (_CENTENAS_FEM if fem else _CENTENAS)[c]


def _cardinal(n: int, fem: bool = False) -> str:
    """0..999999 por extenso. `fem` concorda o número com substantivo feminino."""
    if n < 1000:
        return "zero" if n == 0 else _grupo(n, fem)
    milhares, resto = divmod(n, 1000)
    mil = "mil" if milhares == 1 else f"{_grupo(milhares, fem)} mil"
    if resto == 0:
        return mil
    # "mil e quinze" / "mil e duzentos" (resto < 100 ou centena redonda); senão sem "e".
    conector = " e " if (resto < 100 or resto % 100 == 0) else " "
    return f"{mil}{conector}{_grupo(resto, fem)}"


# --- passos da conversão (ordem importa) ---
_RE_DATA = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
_RE_MOEDA = re.compile(r"R\$\s?(\d{1,3}(?:\.\d{3})*|\d+),(\d{2})")
_RE_REFID = re.compile(r"\b\d{7,}\b")
# Inteiro "solto": NÃO adjacente a "/" (assim uma data inválida tipo 45/13/2026 — que o
# passo de datas deixou intacta — não tem o dia/mês cardinalizados por engano).
_RE_INTEIRO = re.compile(r"(?<![\d/])(\d{1,6})(?![\d/])([ \t]+[A-Za-zÀ-ÿ]+)?")


def _converter_datas(texto: str) -> str:
    def repl(m: re.Match[str]) -> str:
        dia, mes, ano = int(m.group(1)), int(m.group(2)), m.group(3)
        if not (1 <= mes <= 12 and 1 <= dia <= 31):
            return m.group(0)  # data inválida: não inventa, deixa como está
        dia_str = "primeiro" if dia == 1 else _cardinal(dia)
        return f"{dia_str} de {_MESES[mes]} de {ano}"  # ano em dígitos (decisão de demo)

    return _RE_DATA.sub(repl, texto)


def _converter_valores(texto: str) -> str:
    def repl(m: re.Match[str]) -> str:
        reais = int(m.group(1).replace(".", ""))
        centavos = int(m.group(2))
        partes: list[str] = []
        if reais:
            partes.append(f"{_cardinal(reais)} {'real' if reais == 1 else 'reais'}")
        if centavos:
            partes.append(f"{_cardinal(centavos)} {'centavo' if centavos == 1 else 'centavos'}")
        return " e ".join(partes) if partes else "zero reais"

    return _RE_MOEDA.sub(repl, texto)


def _converter_refids(texto: str) -> str:
    # 7+ dígitos = identificador (RefId): lê dígito a dígito, não vira cardinal.
    return _RE_REFID.sub(lambda m: " ".join(_DIGITO[d] for d in m.group(0)), texto)


def _converter_inteiros(texto: str) -> str:
    def repl(m: re.Match[str]) -> str:
        num, seguinte = m.group(1), m.group(2) or ""
        n = int(num)
        if len(num) == 4 and 1900 <= n <= 2099:
            return m.group(0)  # ano solto: preserva os dígitos
        fem = seguinte.strip().lower() in _SUBST_FEMININOS
        return f"{_cardinal(n, fem)}{seguinte}"

    return _RE_INTEIRO.sub(repl, texto)


def para_fala(texto: str) -> str:
    """Texto formatado -> texto falável. Degrada para o original em QUALQUER erro."""
    if not texto:
        return texto
    try:
        s = _converter_datas(texto)
        s = _converter_valores(s)
        s = _converter_refids(s)
        return _converter_inteiros(s)
    except Exception:  # noqa: BLE001 - SEGURO: conversão nunca derruba o áudio (fala o texto formatado)
        return texto
