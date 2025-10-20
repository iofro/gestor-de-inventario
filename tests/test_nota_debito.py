import pytest
from decimal import Decimal

import utils.catalogos as catalogos

from db import DB
from dte import generar_dte_json
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


def test_nde_docrel_control_ccf(monkeypatch):
    monkeypatch.setattr(
        "svfe.config.load_datos_negocio",
        lambda: {"direccion": {"departamento": "05", "municipio": "24", "complemento": "Dir"}},
    )
    monkeypatch.setattr("dte.validate_dte_json", lambda *a, **k: None)
    monkeypatch.setattr(
        "dte._build_receptor_direccion",
        lambda src: {"departamento": "05", "municipio": "24", "complemento": "Dir"},
    )

    db = create_db()
    dte_origen = {
        "identificacion": {
            "tipoDte": "03",
            "codigoGeneracion": "12345678-1234-1234-1234-1234567890AB",
            "numeroControl": "DTE-03-S001P001-000000000000999",
            "fecEmi": "2024-02-01",
            "ambiente": "00",
        },
        "emisor": {
            "nit": "06141407100012",
            "nrc": "1234567",
            "nombre": "Emisor Pruebas",
            "codActividad": "123456",
            "descActividad": "Venta",
            "tipoEstablecimiento": "01",
            "telefono": "22223333",
            "correo": "emisor@example.com",
            "direccion": {"departamento": "05", "municipio": "24", "complemento": "Dir"},
        },
        "receptor": {
            "nombre": "Cliente",
            "nit": "06141407100012",
            "nrc": "7654321",
            "codActividad": "654321",
            "descActividad": "Servicios",
            "direccion": {"departamento": "05", "municipio": "24", "complemento": "Dir Cliente"},
        },
        "resumen": {
            "totalGravada": 10,
            "totalExenta": 0,
            "totalNoSuj": 0,
            "montoTotalOperacion": 10,
        },
        "cuerpoDocumento": [
            {
                "numItem": 1,
                "tipoItem": 1,
                "codigo": "ITEM1",
                "descripcion": "Servicio",
                "cantidad": 1,
                "uniMedida": 59,
                "precioUni": 10,
                "ventaGravada": 10,
                "ventaExenta": 0,
                "ventaNoSuj": 0,
                "tributos": [catalogos.TRIBUTO_IVA],
            }
        ],
    }

    nde = generar_nde_desde_dte(db, dte_origen, None, 5.0, "Ajuste", ambiente="00")
    numero_control = dte_origen["identificacion"]["numeroControl"].upper()
    doc_rel = nde["documentoRelacionado"][0]
    assert doc_rel["numeroDocumento"] == numero_control
    assert doc_rel["tipoGeneracion"] == 1
    for item in nde["cuerpoDocumento"]:
        assert item["numeroDocumento"] == numero_control


def test_nde_unimedida_default(monkeypatch):
    monkeypatch.setattr(
        "svfe.config.load_datos_negocio",
        lambda: {"direccion": {"departamento": "05", "municipio": "24", "complemento": "Dir"}},
    )
    monkeypatch.setattr("dte.validate_dte_json", lambda *a, **k: None)
    monkeypatch.setattr(
        "dte._build_receptor_direccion",
        lambda src: {"departamento": "05", "municipio": "24", "complemento": "Dir"},
    )

    db = create_db()
    dte_origen = {
        "identificacion": {
            "tipoDte": "03",
            "codigoGeneracion": "12345678-ABCD-1234-ABCD-1234567890AB",
            "numeroControl": "DTE-03-S001P001-000000000000777",
            "fecEmi": "2024-03-01",
            "ambiente": "00",
        },
        "emisor": {
            "nit": "06141407100012",
            "nrc": "1234567",
            "nombre": "Emisor",
            "codActividad": "123456",
            "descActividad": "Venta",
            "tipoEstablecimiento": "01",
            "telefono": "22223333",
            "correo": "emisor@example.com",
            "direccion": {"departamento": "05", "municipio": "24", "complemento": "Dir"},
        },
        "receptor": {
            "nombre": "Cliente",
            "nit": "06141407100012",
            "nrc": "7654321",
            "codActividad": "654321",
            "descActividad": "Servicios",
            "direccion": {"departamento": "05", "municipio": "24", "complemento": "Dir Cliente"},
        },
        "resumen": {
            "totalGravada": 10,
            "totalExenta": 0,
            "totalNoSuj": 0,
            "montoTotalOperacion": 10,
        },
        "cuerpoDocumento": [
            {
                "numItem": 1,
                "tipoItem": 1,
                "codigo": "ITEM2",
                "descripcion": "Servicio",
                "cantidad": 1,
                "uniMedida": 59,
                "precioUni": 10,
                "ventaGravada": 10,
                "ventaExenta": 0,
                "ventaNoSuj": 0,
                "tributos": [catalogos.TRIBUTO_IVA],
            }
        ],
    }

    detalles = [
        {
            "codigo": "ITEM2",
            "descripcion": "Ajuste",
            "ajuste": "5",
            "ventas_gravadas": Decimal("5"),
            "uniMedida": None,
        }
    ]

    nde = generar_nde_desde_dte(db, dte_origen, detalles, None, "Ajuste", ambiente="00")
    assert nde["cuerpoDocumento"][0]["uniMedida"] == 59


def test_generar_nde_detalle_ajuste_cantidad(monkeypatch):
    monkeypatch.setattr(
        "svfe.config.load_datos_negocio",
        lambda: {"direccion": {"departamento": "05", "municipio": "24", "complemento": "Dir"}},
    )
    monkeypatch.setattr("dte.validate_dte_json", lambda *a, **k: None)
    monkeypatch.setattr(
        "dte._build_receptor_direccion",
        lambda src: {"departamento": "05", "municipio": "24", "complemento": "Dir"},
    )

    db = create_db()
    db.add_vendedor("V1")
    vid = db.cursor.lastrowid
    db.add_producto("Prod", "P1", None, vid, None, 0, 0, 0, 10)
    pid = db.cursor.lastrowid
    venta_id = db.add_venta("2024-01-01", 50)
    db.add_detalle_venta(venta_id, pid, 5, 10, vendedor_id=vid)
    dte_origen = generar_dte_json(db, venta_id, tipo_dte="01")
    codigo = dte_origen["cuerpoDocumento"][0]["codigo"]
    detalles = [
        {
            "codigo": codigo,
            "descripcion": "Prod",
            "cantidad": 3,
            "precio_unitario": 10,
            "afectacion": "gravada",
            "ajusteCantidad": True,
        }
    ]

    nde = generar_nde_desde_dte(db, dte_origen, detalles, None, "Ajuste", ambiente="00")
    item = nde["cuerpoDocumento"][0]
    assert Decimal(str(item["cantidad"])) == Decimal("3.0000")
    assert Decimal(str(item["ventaGravada"])) == Decimal("30.0000")
    assert Decimal(str(item["precioUni"])) == Decimal("10.0000")
    assert Decimal(str(nde["resumen"]["montoTotalOperacion"])) == Decimal("33.90")
