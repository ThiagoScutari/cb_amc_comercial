"""Testes do conversor texto-formatado -> texto-falável (app/voice/fala.py).

Determinísticos, sem rede. `para_fala` roda no dispatcher ANTES do TTS: o texto
(formatado: dígitos, R$ 0.000,00, dd/mm/aaaa) vira fala (números/datas por extenso),
preservando a porta única (o áudio é derivado do MESMO texto). Cobre só o NOSSO
domínio (inteiros até ~milhares, valores R$, datas, RefId, ano), não o universo.
"""

from app.voice.fala import para_fala


# ---------- quantidades + gênero (lista curada de substantivos femininos) ----------
def test_quantidade_feminina_concorda():
    assert para_fala("200 peças") == "duzentas peças"


def test_quantidade_masculina_default():
    assert para_fala("200 itens") == "duzentos itens"


def test_singular_feminino():
    assert para_fala("1 peça") == "uma peça"


def test_singular_masculino():
    assert para_fala("1 item") == "um item"


def test_unidades_e_caixas_femininos():
    assert para_fala("2 unidades") == "duas unidades"
    assert para_fala("3 caixas") == "três caixas"


# ---------- valores em reais (APROXIMADOS no áudio; o texto ao cliente fica exato) ----------
def test_valor_milhares_arredonda_a_centena_com_cerca_de():
    # antes era exato ('...seiscentos e doze reais'); agora arredonda à centena p/ fala leve
    assert para_fala("R$ 38.612,00") == "cerca de trinta e oito mil e seiscentos reais"


def test_valor_milhares_com_centavos_arredonda_e_descarta_centavos():
    out = para_fala("R$ 5.791,80")
    assert "cerca de" in out and "cinco mil" in out and "oitocentos" in out
    assert "oitenta" not in out  # centavos NÃO são falados na aproximação


def test_valor_reais_e_centavos_arredonda_a_centena():
    # 1.234,56 -> milhares arredonda à centena (1200); centavos somem
    assert para_fala("R$ 1.234,56") == "cerca de mil e duzentos reais"


def test_valor_um_real_singular_fica_exato():
    # < 100 reais é curto: mantém exato (sem 'cerca de'), centavos zero não somam nada
    assert para_fala("R$ 1,00") == "um real"


def test_valor_so_centavos_mantem_fala_dos_centavos():
    # sub-1-real: arredondar zeraria o valor -> mantém a fala dos centavos (como antes)
    assert para_fala("R$ 0,50") == "cinquenta centavos"


def test_valor_um_centavo_singular():
    assert para_fala("R$ 0,01") == "um centavo"


def test_arredonda_so_a_moeda_preserva_pedido_e_data():
    # CRÍTICO: arredondamento é SÓ p/ moeda. Nº de pedido e data passam intactos.
    out = para_fala("Pedido 5001 no valor de R$ 5.791,80 para 13/06/2026.")
    assert "cinco mil e um" in out  # pedido: cardinal EXATO, não arredondado p/ 'cinco mil'
    assert "cerca de" in out and "cinco mil e oitocentos reais" in out  # moeda: aproximada
    assert "treze de junho de 2026" in out  # data intacta
    assert "oitenta" not in out  # centavos da moeda somem


def test_data_e_pedido_sozinhos_nao_levam_cerca_de():
    # sem moeda no texto, nada de 'cerca de' nem arredondamento (sem regressão)
    out = para_fala("Pedido 5001 confirmado para 13/06/2026.")
    assert "cinco mil e um" in out and "treze de junho de 2026" in out
    assert "cerca de" not in out


def test_arredondamento_que_falha_degrada_para_o_texto_original(monkeypatch):
    # formato inesperado no arredondamento -> para_fala cai no texto original, sem levantar
    import app.voice.fala as fala

    def explode(*_a, **_k):
        raise RuntimeError("formato inesperado")

    monkeypatch.setattr(fala, "_arredondar_reais", explode)
    assert para_fala("R$ 5.791,80") == "R$ 5.791,80"


# ---------- datas dd/mm/aaaa (ano em dígitos) ----------
def test_data_por_extenso_ano_em_digitos():
    assert para_fala("28/06/2026") == "vinte e oito de junho de 2026"


def test_data_invalida_fica_como_esta():
    # mês 13 não existe -> não converte (degrada sem inventar)
    assert para_fala("45/13/2026") == "45/13/2026"


# ---------- RefId: 7+ dígitos lidos dígito a dígito ----------
def test_refid_digito_a_digito():
    assert para_fala("340103413") == "três quatro zero um zero três quatro um três"


# ---------- ano solto (1900-2099) preservado em dígitos ----------
def test_ano_solto_preservado():
    assert para_fala("2026") == "2026"


# ---------- frase integrada (o caso real da demo) ----------
def test_frase_completa_da_demo():
    entrada = "Seu pedido tem 200 peças, no valor de R$ 38.612,00, com entrega em 28/06/2026."
    esperado = (
        "Seu pedido tem duzentas peças, no valor de cerca de trinta e oito mil e seiscentos "
        "reais, com entrega em vinte e oito de junho de 2026."
    )
    assert para_fala(entrada) == esperado


# ---------- SEGURO: qualquer erro degrada para o texto original ----------
def test_erro_interno_degrada_para_o_texto_original(monkeypatch):
    # Se a conversão quebrar, o áudio NUNCA pode falhar por causa disso: devolve o
    # texto formatado inalterado (no pior caso, o TTS fala os números formatados).
    import app.voice.fala as fala

    def explode(*_a, **_k):
        raise RuntimeError("boom")

    monkeypatch.setattr(fala, "_converter_valores", explode)
    assert para_fala("R$ 1,00") == "R$ 1,00"


def test_texto_sem_numeros_inalterado():
    assert para_fala("Oi, tudo bem? Posso ajudar.") == "Oi, tudo bem? Posso ajudar."


# ---------- S18a: valores grandes (milhão/bilhão) — a engorda da S17 criou valores de milhão ----
def test_valor_milhao_da_demo():
    # R$ 1.282.540,70 (pedido real da demo): ANTES degradava a frase TODA pro cru; agora fala
    out = para_fala("R$ 1.282.540,70")
    assert "R$" not in out and "1.282.540" not in out
    assert out == "cerca de um milhão duzentos e oitenta e dois mil e quinhentos reais"


def test_valor_milhoes_da_demo():
    out = para_fala("R$ 2.603.247,50")
    assert out == "cerca de dois milhões seiscentos e três mil e duzentos reais"


def test_cardinal_bordas_do_milhao():
    from app.voice.fala import _cardinal

    assert _cardinal(999999) == "novecentos e noventa e nove mil novecentos e noventa e nove"
    assert _cardinal(1_000_000) == "um milhão"
    assert _cardinal(1_002_000) == "um milhão e dois mil"  # zeros intermediários
    assert _cardinal(2_000_000) == "dois milhões"  # plural


def test_cardinal_bilhao_por_seguranca():
    from app.voice.fala import _cardinal

    assert _cardinal(1_000_000_000) == "um bilhão"
    assert _cardinal(2_000_000_000) == "dois bilhões"


def test_milhao_nao_envenena_o_resto_da_frase():
    # REGRESSÃO do bug A1: um valor de milhão não pode mais deixar pedido/data crus pro TTS.
    entrada = "Pedido 4477 entregue, no valor de R$ 1.282.540,70, em 07/05/2026."
    out = para_fala(entrada)
    assert "quatro mil quatrocentos e setenta e sete" in out  # pedido convertido
    assert "milhão" in out  # valor convertido
    assert "sete de maio de 2026" in out  # data convertida
    assert "R$" not in out and "1.282.540" not in out  # nada cru sobrou


# ---------- S18a: blindagem POR TOKEN (uma falha não contamina o resto) ----------
def test_blindagem_por_token_nao_contamina_a_frase(monkeypatch):
    # Um valor que faz _cardinal explodir cai pro cru SOZINHO; o resto da frase é normalizado.
    # (No código antigo, o try/except GLOBAL derrubaria a frase inteira — efeito-dominó.)
    import app.voice.fala as fala

    real = fala._cardinal

    def parcial(n, fem=False):
        if n == 5800:  # valor arredondado de R$ 5.791,80
            raise RuntimeError("boom só nesse token")
        return real(n, fem)

    monkeypatch.setattr(fala, "_cardinal", parcial)
    out = para_fala("R$ 5.791,80 e 200 peças em 28/06/2026")
    assert "R$ 5.791,80" in out  # token que falhou: fica cru
    assert "duzentas peças" in out  # OUTRO token: convertido, não contaminado
    assert "vinte e oito de junho de 2026" in out  # data: convertida


# ---------- S18a: filtro de códigos não-vocalizáveis (SÓ no áudio) ----------
def test_filtra_codigo_de_rastreio():
    out = para_fala("Seu rastreio é BR600030001BR, certo?")
    assert "BR600030001BR" not in out
    assert "rastreio está na mensagem escrita" in out


def test_filtra_linha_digitavel():
    linha = "47690.00001 02603.247503 00000.000017 8 95670000260324"
    out = para_fala(f"A linha digitável é {linha}.")
    assert "47690" not in out and "260324" not in out
    assert "linha digitável está na mensagem escrita" in out


def test_filtra_chave_de_acesso_44_digitos():
    chave = "3" * 44
    out = para_fala(f"A chave de acesso é {chave}.")
    assert chave not in out
    assert "chave de acesso está na mensagem escrita" in out


def test_codigos_nao_sobram_como_digitos_no_audio():
    import re as _re

    out = para_fala("rastreio BR600030001BR e chave " + "1" * 44)
    assert not _re.search(r"\d", out)  # nenhum dígito dos códigos vaza pra fala


def test_refid_curto_nao_e_confundido_com_codigo():
    # RefId de 9 dígitos NÃO é código longo: segue dígito a dígito (não vira a frase curta).
    assert para_fala("340103413") == "três quatro zero um zero três quatro um três"


def test_audio_only_a_tela_mantem_o_codigo():
    # para_fala é a transformação SÓ do áudio (router:252). A string original — o que a TELA
    # mostra (router:248, resposta crua) — não é mutada: o código completo permanece nela.
    tela = "Seu rastreio é BR600030001BR."
    audio = para_fala(tela)
    assert "BR600030001BR" in tela and "BR600030001BR" not in audio


def test_determinismo_mesmo_input_mesma_saida():
    entrada = "Pedido 4477, R$ 1.282.540,70, rastreio BR600030001BR, em 07/05/2026."
    assert para_fala(entrada) == para_fala(entrada)
