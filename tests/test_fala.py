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


# ---------- valores em reais ----------
def test_valor_milhares_sem_centavos():
    assert para_fala("R$ 38.612,00") == "trinta e oito mil seiscentos e doze reais"


def test_valor_um_real_singular():
    assert para_fala("R$ 1,00") == "um real"


def test_valor_so_centavos():
    assert para_fala("R$ 0,50") == "cinquenta centavos"


def test_valor_reais_e_centavos():
    assert (
        para_fala("R$ 1.234,56")
        == "mil duzentos e trinta e quatro reais e cinquenta e seis centavos"
    )


def test_valor_um_centavo_singular():
    assert para_fala("R$ 0,01") == "um centavo"


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
