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


# ---------- S19a-A: valores -> inteiro CHEIO, centavo TRUNCADO, 'cerca de' só quando trunca ----
def test_valor_inteiro_cheio_centavo_truncado_com_cerca_de():
    # R$ 50.474,90 -> inteiro cheio 50474 (centavo descartado), com 'cerca de'
    assert (
        para_fala("R$ 50.474,90") == "cerca de cinquenta mil quatrocentos e setenta e quatro reais"
    )


def test_valor_milhao_inteiro_cheio_truncado():
    assert (
        para_fala("R$ 1.282.540,70")
        == "cerca de um milhão duzentos e oitenta e dois mil quinhentos e quarenta reais"
    )


def test_valor_exato_sem_centavo_nao_leva_cerca_de():
    assert para_fala("R$ 50.000,00") == "cinquenta mil reais"
    assert para_fala("R$ 38.612,00") == "trinta e oito mil seiscentos e doze reais"


def test_valor_com_centavo_leva_cerca_de_e_inteiro_cheio():
    assert para_fala("R$ 5.791,80") == "cerca de cinco mil setecentos e noventa e um reais"
    assert para_fala("R$ 1.234,56") == "cerca de mil duzentos e trinta e quatro reais"


def test_centavo_e_truncado_nunca_arredondado_pra_cima():
    # 50.474,90 -> ...e quatro (474); JAMAIS ...e cinco (475)
    out = para_fala("R$ 50.474,90")
    assert "setenta e quatro reais" in out and "setenta e cinco" not in out


def test_valor_um_real_singular():
    assert para_fala("R$ 1,00") == "um real"


def test_valor_so_centavos_mantem_fala_dos_centavos():
    # sub-R$ 1: truncar zeraria o valor -> mantém a fala dos centavos
    assert para_fala("R$ 0,50") == "cinquenta centavos"


def test_valor_um_centavo_singular():
    assert para_fala("R$ 0,01") == "um centavo"


def test_valor_so_a_moeda_preserva_data():
    out = para_fala("No valor de R$ 5.791,80 para 13/06/2026.")
    assert "cerca de cinco mil setecentos e noventa e um reais" in out
    assert "treze de junho de 2026" in out  # data intacta
    assert "oitenta" not in out  # centavos da moeda somem


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
        "Seu pedido tem duzentas peças, no valor de trinta e oito mil seiscentos e doze "
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
    # R$ 1.282.540,70 (pedido real da demo): inteiro CHEIO, centavo truncado (S19a)
    out = para_fala("R$ 1.282.540,70")
    assert "R$" not in out and "1.282.540" not in out
    assert out == "cerca de um milhão duzentos e oitenta e dois mil quinhentos e quarenta reais"


def test_valor_milhoes_da_demo():
    out = para_fala("R$ 2.603.247,50")
    assert out == "cerca de dois milhões seiscentos e três mil duzentos e quarenta e sete reais"


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
        if n == 5791:  # inteiro cheio de R$ 5.791,80 (S19a: sem arredondar)
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


# ---------- S19a-B: número de documento (cardinal s/ zero interno; dígito-a-dígito c/ zero) ----
def test_nf_com_zero_interno_vira_digito_a_digito():
    # cardinal emborraria ("sessenta mil e dois"); dígito-a-dígito deixa os zeros audíveis
    assert para_fala("nota 60002") == "nota seis zero zero zero dois"
    assert para_fala("NF 60003") == "NF seis zero zero zero três"
    assert para_fala("título 70013") == "título sete zero zero um três"
    assert para_fala("boleto 60005") == "boleto seis zero zero zero cinco"


def test_nota_fiscal_dois_termos_dispara_pela_palavra_fiscal():
    assert para_fala("nota fiscal 60005") == "nota fiscal seis zero zero zero cinco"


def test_documento_sem_zero_interno_fica_cardinal():
    assert para_fala("pedido 4471") == "pedido quatro mil quatrocentos e setenta e um"
    assert para_fala("pedido 4452") == "pedido quatro mil quatrocentos e cinquenta e dois"


def test_pedido_com_zero_interno_vira_digitos_melhora_read_back():
    # 5001 tem zero interno -> dígito-a-dígito (read-back da S15 fica claro)
    assert para_fala("pedido 5001") == "pedido cinco zero zero um"


def test_regra_documento_so_dispara_com_palavra_chave_quantidade_intacta():
    # sem palavra-chave de documento, é quantidade -> cardinal com gênero (NÃO dígito-a-dígito)
    assert para_fala("200 peças") == "duzentas peças"
    assert para_fala("tenho 200 peças") == "tenho duzentas peças"


def test_valor_em_reais_nao_e_tratado_como_documento():
    # 60.002 dentro de um R$ é VALOR (cardinal), não documento (dígitos)
    assert para_fala("R$ 60.002,00") == "sessenta mil e dois reais"


def test_ano_apos_palavra_chave_e_preservado():
    # número de 4 dígitos 1900-2099 logo após palavra-chave é ano, não documento -> preserva
    assert para_fala("número 2026") == "número 2026"


def test_quantidade_apos_keyword_nao_quebra_genero_quando_ha_separador():
    # "pedido de 200 peças": 'pedido' seguido de 'de' (não-dígito) -> NÃO dispara doc;
    # 200 segue como quantidade feminina
    assert para_fala("pedido de 200 peças") == "pedido de duzentas peças"
