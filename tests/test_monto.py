from utils.monto import monto_a_texto_sv


def num2words(n, lang='es'):
    mapping = {0: 'cero', 174: 'ciento setenta y cuatro'}
    return mapping.get(n, str(n))


def test_monto_a_texto_sv_basic(monkeypatch):
    monkeypatch.setattr('utils.monto.num2words', num2words)
    assert monto_a_texto_sv(174.50) == "CIENTO SETENTA Y CUATRO 50/100 DÓLARES"


def test_monto_a_texto_sv_cents(monkeypatch):
    monkeypatch.setattr('utils.monto.num2words', num2words)
    assert monto_a_texto_sv(0.99) == "CERO 99/100 DÓLARES"
