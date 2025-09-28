import pytest

from db import DB
from nota_debito_electronica import generar_nde_desde_dte


def create_db():
    return DB(":memory:")


@pytest.fixture(autouse=True)
def _mock_geo(monkeypatch):
    monkeypatch.setattr(
        "dte.validar_dep_muni_por_catalogo",
        lambda d, m, strict=True: (str(d).zfill(2), str(m).zfill(2)),
    )


def test_generar_nde_consumidor_final_dui_en_nit(monkeypatch):
    monkeypatch.setattr(
        "svfe.config.load_datos_negocio",
        lambda: {"direccion": {"departamento": "05", "municipio": "24", "complemento": "Dir"}},
    )
    monkeypatch.setattr("dte.validate_dte_json", lambda *a, **k: None)
    monkeypatch.setattr(
        "dte._build_receptor_direccion",
        lambda src: {
            "departamento": str(src.get("departamento", "05")).zfill(2),
            "municipio": str(src.get("municipio", "24")).zfill(2),
            "complemento": src.get("complemento", "Dir"),
        },
    )

    db = create_db()
    dte_origen = {
        "identificacion": {
            "tipoDte": "01",
            "codigoGeneracion": "12345678-1234-1234-1234-1234567890AB",
            "fecEmi": "2024-01-01",
        },
        "emisor": {},
        "receptor": {
            "nombre": "Consumidor Final",
            "tipoDocumento": "13",
            "numDocumento": "01234567-8",
        },
        "cuerpoDocumento": [
            {
                "numItem": 1,
                "tipoItem": 1,
                "descripcion": "Servicio",
                "cantidad": 1,
                "uniMedida": 59,
                "precioUni": 1.0,
                "montoDescu": 0.0,
                "ventaGravada": 1.0,
                "ventaExenta": 0.0,
                "ventaNoSuj": 0.0,
                "tributos": [],
            }
        ],
        "resumen": {
            "totalNoSuj": 0.0,
            "totalExenta": 0.0,
            "totalGravada": 1.0,
            "subTotal": 1.0,
            "subTotalVentas": 1.0,
            "descuNoSuj": 0.0,
            "descuExenta": 0.0,
            "descuGravada": 0.0,
            "totalDescu": 0.0,
            "ivaPerci1": 0.0,
            "ivaRete1": 0.0,
            "reteRenta": 0.0,
            "condicionOperacion": 1,
            "tributos": [],
            "montoTotalOperacion": 1.0,
            "totalLetras": "UNO",
        },
    }

    nde = generar_nde_desde_dte(db, dte_origen, None, 1.0, None, ambiente="00")
    receptor = nde["receptor"]
    assert receptor["nit"] == "012345678"
    assert "nrc" in receptor
    assert receptor["nrc"] is None
