from db import DB
from dte import generar_nde_desde_dte


def create_db():
    return DB(":memory:")


def test_generar_nde_desde_dte_wrapper_config_produccion(monkeypatch):
    datos = {
        "nit": "0614-140710-001-2",
        "nrc": "1234567",
        "nombre": "Emisor",
        "nombreComercial": "Emisor",
        "codActividad": "111111",
        "descActividad": "Giro",
        "telefono": "22223456",
        "correo": "test@example.com",
        "direccion": {"departamento": "05", "municipio": "24", "complemento": "Dir"},
        "dte_api": {"prefijo_control": "DTE-01-S001P001"},
    }

    monkeypatch.setattr("dte._load_dte_api_config", lambda: {"ambiente": "produccion"})
    monkeypatch.setattr("dte._load_datos_negocio", lambda: datos)
    monkeypatch.setattr("svfe.config.load_datos_negocio", lambda: datos)

    db = create_db()
    dte_origen = {
        "identificacion": {
            "tipoDte": "03",
            "codigoGeneracion": "12345678-1234-1234-1234-1234567890AB",
            "numeroControl": "DTE-03-S001P001-000000001",
            "fecEmi": "2024-01-01",
        },
        "emisor": {"nit": "06141407100012", "nrc": "1234567"},
        "receptor": {
            "nombre": "Cliente",
            "tipoDocumento": "36",
            "numDocumento": "06141407100012",
            "nrc": "1234567",
        },
        "resumen": {
            "totalNoSuj": 0.0,
            "totalExenta": 0.0,
            "totalGravada": 1.0,
            "subTotal": 1.0,
            "subTotalVentas": 1.0,
            "montoTotalOperacion": 1.0,
            "totalPagar": 1.0,
            "condicionOperacion": 1,
            "tributos": [],
            "totalLetras": "UNO",
        },
    }

    nde = generar_nde_desde_dte(db, dte_origen, None, 1.0, "Ajuste", ambiente="00")

    assert nde["identificacion"]["ambiente"] == "01"
