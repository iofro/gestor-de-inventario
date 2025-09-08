import importlib
import sys

import pytest
from decimal import Decimal


def test_monto_a_texto_sv_import_error(monkeypatch):
    # Ensure num2words is missing and module reload uses fallback
    sys.modules.pop("utils.monto", None)
    monkeypatch.setitem(sys.modules, "num2words", None)
    monto = importlib.import_module("utils.monto")
    importlib.reload(monto)
    with pytest.raises(ImportError):
        monto.monto_a_texto_sv(10)


def test_monto_a_texto_sv_decimal_precision():
    from utils import monto as monto_mod
    import importlib as il

    il.reload(monto_mod)
    monto = Decimal("2.6750")
    original = Decimal(monto)  # ensure unchanged
    texto = monto_mod.monto_a_texto_sv(monto)
    assert texto == "DOS 68/100 DÓLARES"
    assert monto == original


def test_numero_a_letras_decimal_precision():
    from dte import numero_a_letras

    monto = Decimal("2.6750")
    texto = numero_a_letras(monto)
    assert texto == "DOS CON 68/100 DÓLARES"
