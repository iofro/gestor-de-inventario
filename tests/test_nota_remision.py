import pytest
import warnings

from db import DB
from nota_remision_electronica import (
    generar_nota_remision_desde_factura,
    generar_nota_remision_independiente,
)
import dte


def _sample_emisor():
    return {"nit": "0614-140710-001-2", "nrc": "1234567"}


def _sample_receptor():
    return {
        "tipoDocumento": "36",
        "numDocumento": "0614-140710-001-2",
        "nrc": "1234567",
        "nombre": "Cliente",
        "bienTitulo": "01",
        "codActividad": "6201",
        "descActividad": "Servicios de software",
        "telefono": "70000001",
        "correo": "cliente@example.com",
        "direccion": {
            "departamento": "05",
            "municipio": "01",
            "complemento": "San Salvador",
        },
    }


def test_nr_desde_factura_documento_relacionado(monkeypatch):
    monkeypatch.setattr("dte._load_datos_negocio", lambda: {"dte_api": {}})
    db = DB(":memory:")
    factura = {
        "identificacion": {
            "tipoDte": "03",
            "codigoGeneracion": "12345678-ABCD-1234-ABCD-1234567890AB",
            "fecEmi": "2024-01-01",
        },
        "emisor": _sample_emisor(),
        "receptor": _sample_receptor(),
        "cuerpoDocumento": [
            {"descripcion": "Prod", "cantidad": 1, "uniMedida": 59}
        ],
    }
    extension = {"docuEntrega": "123", "docuRecibe": "456"}
    data = generar_nota_remision_desde_factura(db, factura, extension=extension)
    doc_rel = data["documentoRelacionado"][0]
    assert doc_rel["tipoDocumento"] == "03"
    assert doc_rel["numeroDocumento"] == "12345678-ABCD-1234-ABCD-1234567890AB"
    item = data["cuerpoDocumento"][0]
    assert item["numeroDocumento"] == "12345678-ABCD-1234-ABCD-1234567890AB"
    assert item["codTributo"] is None
    assert float(item["precioUni"]) == 0.0
    assert float(item["ventaNoSuj"]) == 0.0
    assert float(item["ventaExenta"]) == 0.0
    assert float(item["ventaGravada"]) == 0.0
    assert "-" not in data["emisor"]["nit"]
    assert " " not in data["receptor"]["numDocumento"]
    rec = data["receptor"]
    assert "nombreComercial" in rec
    assert rec["nombreComercial"] is None
    resumen = data["resumen"]
    assert float(resumen["descuNoSuj"]) == 0.0
    assert float(resumen["descuExenta"]) == 0.0
    assert float(resumen["descuGravada"]) == 0.0


def test_nr_desde_factura_extension(monkeypatch):
    monkeypatch.setattr("dte._load_datos_negocio", lambda: {"dte_api": {}})
    db = DB(":memory:")
    factura = {
        "identificacion": {
            "tipoDte": "03",
            "codigoGeneracion": "12345678-ABCD-1234-ABCD-1234567890AB",
            "fecEmi": "2024-01-01",
        },
        "emisor": _sample_emisor(),
        "receptor": _sample_receptor(),
        "cuerpoDocumento": [{"descripcion": "Prod", "cantidad": 1, "uniMedida": 59}],
    }
    extension = {
        "nombEntrega": "Juan",
        "docuEntrega": "123",
        "nombRecibe": "Ana",
        "docuRecibe": "456",
        "observaciones": "Obs",
    }
    data = generar_nota_remision_desde_factura(
        db, factura, extension=extension
    )
    assert data["extension"]["nombEntrega"] == "Juan"
    rec = data["receptor"]
    assert "nombreComercial" in rec
    assert rec["nombreComercial"] is None


def test_nr_desde_factura_extension_actualiza_receptor(monkeypatch):
    monkeypatch.setattr("dte._load_datos_negocio", lambda: {"dte_api": {}})
    db = DB(":memory:")
    factura = {
        "identificacion": {
            "tipoDte": "03",
            "codigoGeneracion": "12345678-ABCD-1234-ABCD-1234567890AB",
            "fecEmi": "2024-01-01",
        },
        "emisor": _sample_emisor(),
        "receptor": {
            "tipoDocumento": "13",
            "numDocumento": "12345678-9",
            "nombre": "Cliente",
            "bienTitulo": "01",
            "codActividad": "6201",
            "descActividad": "Servicios de software",
            "telefono": "70000001",
            "correo": "cliente@example.com",
            "direccion": {
                "departamento": "05",
                "municipio": "01",
                "complemento": "San Salvador",
            },
        },
        "cuerpoDocumento": [{"descripcion": "Prod", "cantidad": 1, "uniMedida": 59}],
    }
    extension = {
        "nombEntrega": "Juan",
        "docuEntrega": "123",
        "nombRecibe": "Ana",
        "docuRecibe": "0614-140710-001-2",
        "tipoDocRecibe": "36",
        "nrcRecibe": "1234567",
    }
    data = generar_nota_remision_desde_factura(db, factura, extension=extension)
    rec = data["receptor"]
    assert rec["tipoDocumento"] == "36"
    assert rec["numDocumento"] == "06141407100012"
    assert rec["nrc"] == "1234567"
    assert "nombreComercial" in rec
    ext = data["extension"]
    assert "tipoDocRecibe" not in ext
    assert "nrcRecibe" not in ext


def test_nr_independiente_extension(monkeypatch):
    monkeypatch.setattr("dte._load_datos_negocio", lambda: {"dte_api": {}})
    db = DB(":memory:")
    emisor = _sample_emisor()
    receptor = _sample_receptor()
    extension = {
        "nombEntrega": "Juan",
        "docuEntrega": "0614-140710-001-2",
        "nombRecibe": "Ana",
        "docuRecibe": "1234 5678",
        "observaciones": "Obs",
    }
    detalles = [{"descripcion": "Prod", "cantidad": 1, "uniMedida": 59}]
    data = generar_nota_remision_independiente(
        db,
        emisor=emisor,
        receptor=receptor,
        detalles=detalles,
        extension=extension,
    )
    assert "documentoRelacionado" not in data
    ext = data["extension"]
    assert ext["nombEntrega"] == "Juan"
    assert ext["nombRecibe"] == "Ana"
    assert ext["docuEntrega"] == "06141407100012"
    assert ext["docuRecibe"] == "12345678"
    assert "-" not in data["emisor"]["nit"]
    assert " " not in data["receptor"]["numDocumento"]
    rec = data["receptor"]
    assert "nombreComercial" in rec
    assert rec["nombreComercial"] is None
    assert data["cuerpoDocumento"][0]["codTributo"] is None
    res = data["resumen"]
    assert float(res["descuNoSuj"]) == 0.0
    assert float(res["descuExenta"]) == 0.0
    assert float(res["descuGravada"]) == 0.0


def test_nr_independiente_extension_sin_observaciones(monkeypatch):
    monkeypatch.setattr("dte._load_datos_negocio", lambda: {"dte_api": {}})
    db = DB(":memory:")
    emisor = _sample_emisor()
    receptor = _sample_receptor()
    extension = {
        "nombEntrega": "Juan",
        "docuEntrega": "0614-140710-001-2",
        "nombRecibe": "Ana",
        "docuRecibe": "1234 5678",
    }
    detalles = [{"descripcion": "Prod", "cantidad": 1, "uniMedida": 59}]
    with pytest.raises(ValueError):
        generar_nota_remision_independiente(
            db,
            emisor=emisor,
            receptor=receptor,
            detalles=detalles,
            extension=extension,
        )


def test_nr_independiente_extension_observaciones_vacia(monkeypatch):
    monkeypatch.setattr("dte._load_datos_negocio", lambda: {"dte_api": {}})
    db = DB(":memory:")
    emisor = _sample_emisor()
    receptor = _sample_receptor()
    extension = {
        "nombEntrega": "Juan",
        "docuEntrega": "0614-140710-001-2",
        "nombRecibe": "Ana",
        "docuRecibe": "1234 5678",
        "observaciones": "   ",
    }
    detalles = [{"descripcion": "Prod", "cantidad": 1, "uniMedida": 59}]
    with pytest.raises(ValueError):
        generar_nota_remision_independiente(
            db,
            emisor=emisor,
            receptor=receptor,
            detalles=detalles,
            extension=extension,
        )


def test_nr_item_validation(monkeypatch):
    monkeypatch.setattr("dte._load_datos_negocio", lambda: {"dte_api": {}})
    db = DB(":memory:")
    emisor = _sample_emisor()
    receptor = _sample_receptor()
    with pytest.raises(ValueError):
        extension = {
            "nombEntrega": "X",
            "docuEntrega": "123",
            "nombRecibe": "Y",
            "docuRecibe": "456",
            "observaciones": "Obs",
        }
        generar_nota_remision_independiente(
            db,
            emisor=emisor,
            receptor=receptor,
            detalles=[{"descripcion": "Prod", "cantidad": 0, "uniMedida": 59}],
            extension=extension,
        )
    extension = {
        "nombEntrega": "X",
        "docuEntrega": "123",
        "nombRecibe": "Y",
        "docuRecibe": "456",
        "observaciones": "Obs",
    }
    data = generar_nota_remision_independiente(
        db,
        emisor=emisor,
        receptor=receptor,
        detalles=[{"descripcion": "Prod", "cantidad": 1, "uniMedida": 1}],
        extension=extension,
    )
    assert data["cuerpoDocumento"][0]["uniMedida"] == 59


def test_receptor_dui_sin_nrc(monkeypatch):
    monkeypatch.setattr("dte._load_datos_negocio", lambda: {"dte_api": {}})
    db = DB(":memory:")
    emisor = _sample_emisor()
    receptor = {
        "tipoDocumento": "13",
        "numDocumento": "12345678-9",
        "nrc": "1234567",
        "nombre": "Cliente",
        "bienTitulo": "01",
        "codActividad": "6201",
        "descActividad": "Servicios de software",
        "telefono": "70000001",
        "correo": "cliente@example.com",
        "direccion": {
            "departamento": "05",
            "municipio": "01",
            "complemento": "San Salvador",
        },
    }
    factura = {
        "identificacion": {"tipoDte": "03", "codigoGeneracion": "1", "fecEmi": "2024-01-01"},
        "emisor": emisor,
        "receptor": receptor,
        "cuerpoDocumento": [{"descripcion": "Prod", "cantidad": 1, "uniMedida": 59}],
    }
    extension = {"docuEntrega": "123", "docuRecibe": "456"}
    with warnings.catch_warnings(record=True) as w:
        data = generar_nota_remision_desde_factura(db, factura, extension=extension)
    rec = data["receptor"]
    assert rec["tipoDocumento"] == "13"
    assert rec["numDocumento"] == "123456789"
    assert "nrc" not in rec
    assert rec["nombreComercial"] is None
    assert any("Se removió NRC" in str(warn.message) for warn in w)


def test_receptor_nit_sin_nrc_error(monkeypatch):
    monkeypatch.setattr("dte._load_datos_negocio", lambda: {"dte_api": {}})
    db = DB(":memory:")
    emisor = _sample_emisor()
    receptor = {
        "tipoDocumento": "36",
        "numDocumento": "0614-140710-001-2",
        "nombre": "Cliente",
        "bienTitulo": "01",
        "codActividad": "6201",
        "descActividad": "Servicios de software",
        "telefono": "70000001",
        "correo": "cliente@example.com",
        "direccion": {
            "departamento": "05",
            "municipio": "01",
            "complemento": "San Salvador",
        },
    }
    extension = {
        "nombEntrega": "Juan",
        "docuEntrega": "0614-140710-001-2",
        "nombRecibe": "Ana",
        "docuRecibe": "1234 5678",
        "observaciones": "Obs",
    }
    detalles = [{"descripcion": "Prod", "cantidad": 1, "uniMedida": 59}]
    with pytest.raises(ValueError):
        generar_nota_remision_independiente(
            db,
            emisor=emisor,
            receptor=receptor,
            detalles=detalles,
            extension=extension,
        )


@pytest.mark.parametrize("campo", ["codActividad", "descActividad", "telefono", "correo"])
def test_receptor_campo_obligatorio_faltante(monkeypatch, campo):
    monkeypatch.setattr("dte._load_datos_negocio", lambda: {"dte_api": {}})
    db = DB(":memory:")
    emisor = _sample_emisor()
    receptor = _sample_receptor()
    receptor.pop(campo)
    detalles = [{"descripcion": "Prod", "cantidad": 1, "uniMedida": 59}]
    extension = {"docuEntrega": "123", "docuRecibe": "456"}
    with pytest.raises(ValueError, match=f"receptor requiere {campo}"):
        generar_nota_remision_independiente(
            db,
            emisor=emisor,
            receptor=receptor,
            detalles=detalles,
            extension=extension,
        )


def test_receptor_direccion_complemento_faltante(monkeypatch):
    monkeypatch.setattr("dte._load_datos_negocio", lambda: {"dte_api": {}})
    db = DB(":memory:")
    emisor = _sample_emisor()
    receptor = _sample_receptor()
    receptor["direccion"].pop("complemento")
    detalles = [{"descripcion": "Prod", "cantidad": 1, "uniMedida": 59}]
    extension = {"docuEntrega": "123", "docuRecibe": "456"}
    with pytest.raises(ValueError, match="receptor requiere direccion.complemento"):
        generar_nota_remision_independiente(
            db,
            emisor=emisor,
            receptor=receptor,
            detalles=detalles,
            extension=extension,
        )
