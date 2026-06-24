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


# Escalas grandes (substantivos masculinos: 'dois milhões', nunca 'duas milhões').
_ESCALAS_GRANDES = {2: ("milhão", "milhões"), 3: ("bilhão", "bilhões")}


def _segmento(g: int, escala: int, fem: bool) -> str:
    """Um grupo de 3 dígitos (g em 1..999) com sua escala: 0=unidade, 1=mil, 2=milhão, 3=bilhão.
    'mil' é invariável e dispensa 'um'; milhão/bilhão são substantivos (fem não se aplica)."""
    if escala == 0:
        return _grupo(g, fem)
    if escala == 1:
        return "mil" if g == 1 else f"{_grupo(g, fem)} mil"
    singular, plural = _ESCALAS_GRANDES[escala]
    return f"um {singular}" if g == 1 else f"{_grupo(g, False)} {plural}"


def _cardinal(n: int, fem: bool = False) -> str:
    """0..999.999.999 por extenso (milhão/bilhão inclusos). `fem` concorda o número com
    substantivo feminino — só nos grupos de unidade e mil ('duzentas mil peças')."""
    if n < 1000:
        return "zero" if n == 0 else _grupo(n, fem)
    triades, resto = [], n  # grupos de 3 dígitos, do menos significativo ao mais
    while resto > 0:
        resto, g = divmod(resto, 1000)
        triades.append(g)
    menor_nz = next(i for i, g in enumerate(triades) if g)  # menor triade não-zero -> regra do "e"
    partes: list[str] = []
    for escala in range(len(triades) - 1, -1, -1):
        g = triades[escala]
        if not g:
            continue
        if partes:  # "e" só antes da MENOR triade não-zero quando < 100 ou centena redonda
            usa_e = escala == menor_nz and (g < 100 or g % 100 == 0)
            partes.append(" e " if usa_e else " ")
        partes.append(_segmento(g, escala, fem))
    return "".join(partes)


# --- passos da conversão (ordem importa) ---
_RE_DATA = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
_RE_MOEDA = re.compile(r"R\$\s?(\d{1,3}(?:\.\d{3})*|\d+),(\d{2})")
_RE_REFID = re.compile(r"\b\d{7,}\b")
# Inteiro "solto": NÃO adjacente a "/", "." ou "," — assim datas inválidas (45/13/2026) e
# números FORMATADOS (ex.: "5.791,80" que sobrou de uma moeda não-convertida pela blindagem)
# não têm os grupos cardinalizados por engano (evita "cinco.setecentos e noventa e um,oitenta").
_RE_INTEIRO = re.compile(r"(?<![\d/.,])(\d{1,6})(?![\d/.,])([ \t]+[A-Za-zÀ-ÿ]+)?")

# Códigos NÃO-vocalizáveis (S18a): soletrar 44+ dígitos é inaudível por natureza. Detecção
# por FORMATO/comprimento (padrão nacional), nunca pelos números da demo. Só o ÁUDIO os troca
# por uma frase; a TELA (router:248, resposta crua) mantém os códigos completos.
_RE_RASTREIO = re.compile(r"\b[A-Za-z]{2}\d{9}[A-Za-z]{2}\b")  # Correios: BR600030001BR
_RE_LINHA_DIGITAVEL = re.compile(  # boleto: 5.5 5.6 5.6 1 14 (47 dígitos), pontos opcionais
    r"\b\d{5}\.?\d{5}\s+\d{5}\.?\d{6}\s+\d{5}\.?\d{6}\s+\d\s+\d{14}\b"
)
_RE_CODIGO_SOLIDO = re.compile(r"\b\d{20,}\b")  # rede de segurança: chave NF-e (44), blocos longos
_FRASE_RASTREIO = "o código de rastreio está na mensagem escrita"
_FRASE_LINHA = "a linha digitável está na mensagem escrita"
_FRASE_CHAVE = "a chave de acesso está na mensagem escrita"


def _seguro(repl):
    """Envolve um callback de `re.sub`: se ele falhar, mantém o trecho ORIGINAL e segue. Um
    token problemático nunca contamina o resto da frase (defesa em profundidade — ver módulo)."""

    def _wrap(m: re.Match[str]) -> str:
        try:
            return repl(m)
        except Exception:  # noqa: BLE001 - contém a falha NO token; o resto da frase continua
            return m.group(0)

    return _wrap


def _filtrar_codigos(texto: str) -> str:
    """Troca códigos longos não-vocalizáveis por uma frase curta (rastreio, linha digitável,
    chave de acesso). Roda ANTES dos demais passos, para os dígitos não virarem soletração."""
    s = _RE_RASTREIO.sub(_FRASE_RASTREIO, texto)
    s = _RE_LINHA_DIGITAVEL.sub(_FRASE_LINHA, s)
    return _RE_CODIGO_SOLIDO.sub(
        lambda m: _FRASE_CHAVE if len(m.group(0)) == 44 else _FRASE_LINHA, s
    )


def _converter_datas(texto: str) -> str:
    def repl(m: re.Match[str]) -> str:
        dia, mes, ano = int(m.group(1)), int(m.group(2)), m.group(3)
        if not (1 <= mes <= 12 and 1 <= dia <= 31):
            return m.group(0)  # data inválida: não inventa, deixa como está
        dia_str = "primeiro" if dia == 1 else _cardinal(dia)
        return f"{dia_str} de {_MESES[mes]} de {ano}"  # ano em dígitos (decisão de demo)

    return _RE_DATA.sub(_seguro(repl), texto)


def _arredondar_reais(reais: int) -> int:
    """Valor em reais (centavos já fora) -> forma falável ARREDONDADA. Milhares -> centena
    ('cinco mil e oitocentos'); centenas -> dezena; < 100 -> exato (já é curto).

    Decisão (porta única): o áudio é leve e aproximado; o valor EXATO acompanha no TEXTO que
    o cliente recebe junto. Vale SÓ para moeda — nunca toca pedido, quantidade, data ou código.
    """
    if reais >= 1000:
        return round(reais / 100) * 100  # casa dos milhares: à centena
    if reais >= 100:
        return round(reais / 10) * 10  # centenas: à dezena (ainda preciso)
    return reais  # < 100: curto o bastante, mantém exato


def _converter_valores(texto: str) -> str:
    """Valor monetário (R$) -> fala APROXIMADA: centavos somem, o valor é arredondado e
    'cerca de' sinaliza a aproximação. SÓ mexe em moeda (R$ + ,dd do _RE_MOEDA) — datas,
    pedidos, quantidades e códigos não passam por aqui. Sub-1-real (só centavos) mantém a
    fala dos centavos (arredondar zeraria o valor)."""

    def repl(m: re.Match[str]) -> str:
        reais = int(m.group(1).replace(".", ""))
        centavos = int(m.group(2))
        if reais == 0:  # ex.: R$ 0,80 -> arredondar daria "zero reais"; fala os centavos
            return f"{_cardinal(centavos)} {'centavo' if centavos == 1 else 'centavos'}"
        falado = _arredondar_reais(reais)
        aproximado = falado != reais or centavos != 0  # rotula só quando NÃO é exato
        prefixo = "cerca de " if aproximado else ""
        return f"{prefixo}{_cardinal(falado)} {'real' if falado == 1 else 'reais'}"

    return _RE_MOEDA.sub(_seguro(repl), texto)


def _converter_refids(texto: str) -> str:
    # 7+ dígitos = identificador (RefId): lê dígito a dígito, não vira cardinal.
    return _RE_REFID.sub(_seguro(lambda m: " ".join(_DIGITO[d] for d in m.group(0))), texto)


def _converter_inteiros(texto: str) -> str:
    def repl(m: re.Match[str]) -> str:
        num, seguinte = m.group(1), m.group(2) or ""
        n = int(num)
        if len(num) == 4 and 1900 <= n <= 2099:
            return m.group(0)  # ano solto: preserva os dígitos
        fem = seguinte.strip().lower() in _SUBST_FEMININOS
        return f"{_cardinal(n, fem)}{seguinte}"

    return _RE_INTEIRO.sub(_seguro(repl), texto)


def para_fala(texto: str) -> str:
    """Texto formatado -> texto falável. Cada passo é blindado POR TOKEN (`_seguro`): um
    trecho que falha cai pro cru sozinho, sem envenenar o resto. O try/except global é só o
    backstop final — conversão nunca derruba o áudio (no pior caso, fala o texto formatado)."""
    if not texto:
        return texto
    try:
        s = _filtrar_codigos(texto)  # remove códigos não-vocalizáveis ANTES de tokenizar
        s = _converter_datas(s)
        s = _converter_valores(s)
        s = _converter_refids(s)
        return _converter_inteiros(s)
    except Exception:  # noqa: BLE001 - backstop final: conversão nunca derruba o áudio
        return texto
