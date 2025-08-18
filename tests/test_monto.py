import importlib
import sys

import pytest


def test_monto_a_texto_sv_import_error(monkeypatch):
    # Ensure num2words is missing and module reload uses fallback
    sys.modules.pop("utils.monto", None)
    monkeypatch.setitem(sys.modules, "num2words", None)
    monto = importlib.import_module("utils.monto")
    importlib.reload(monto)
    with pytest.raises(ImportError):
        monto.monto_a_texto_sv(10)
