

from tools.verificar_totales import check_document

def _sample_doc():
    return {
        "identificacion": {"ambiente": "00", "tipoDte": "01"},
        "cuerpoDocumento": [
            {"cantidad": 2, "precioUnitario": 1.5},
            {"cantidad": 1, "precioUnitario": 2.0},
        ],
        "resumen": {
            "totalNoSuj": 0,
            "totalExenta": 0,
            "totalGravada": 5.0,
            "subTotalVentas": 5.0,
            "descuNoSuj": 0,
            "descuExenta": 0,
            "descuGravada": 0,
            "totalDescu": 0,
            "subTotal": 5.0,
            "montoTotalOperacion": 5.0,
            "totalIva": 0.0,
            "totalPagar": 5.0,
        },
    }


def test_check_document_ok():
    doc = _sample_doc()
    assert check_document(doc, expected_ambiente="00") == []


def test_check_document_totals_mismatch():
    doc = _sample_doc()
    doc["resumen"]["totalGravada"] = 6.0
    errors = check_document(doc, expected_ambiente="00")
    assert any("totalGravada" in e for e in errors)


def test_check_document_ambiente_mismatch():
    doc = _sample_doc()
    doc["identificacion"]["ambiente"] = "01"
    errors = check_document(doc, expected_ambiente="00")
    assert any("ambiente" in e for e in errors)
