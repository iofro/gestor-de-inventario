import os
from pathlib import Path
import dte


def test_finalize_pendiente_preserves_original_name(tmp_path, monkeypatch):
    data = {
        "identificacion": {
            "tipoDte": "05",
            "codigoGeneracion": "ABC",
            "numeroControl": "DTE-05-ABC-1",
            "fecEmi": "2024-01-02",
        },
        "receptor": {"nombre": "Cliente"},
        "resumen": {"totalLetras": "X"},
    }
    monkeypatch.setattr(dte, "__file__", str(tmp_path / "dte.py"))
    expected = "20240102_Cliente_DTE-05-ABC-000000000000001_NotaCredito.json"
    pend_path = dte.save_dte_json(data, filename=expected)
    final_path = dte._finalize_pendiente(pend_path, data, "TOKEN", "Transmitido")
    assert os.path.basename(final_path) == expected
    assert Path(final_path).exists()
