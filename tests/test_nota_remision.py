import pytest

from db import DB
from nota_remision_electronica import (
    generar_nota_remision_desde_factura,
    generar_nota_remision_independiente,
)
import dte


def _sample_emisor():
    return {"nit": "0614-140710-001-2", "nrc": "1234567"}


def _sample_receptor():
    return {"tipoDocumento": "36", "numDocumento": "1234 567-8", "nombre": "Cliente"}


def test_nr_desde_factura_documento_relacionado(monkeypatch):
    monkeypatch.setattr("dte._load_datos_negocio", lambda: {"dte_api": {}})
    db = DB(":memory:")
    factura = {
        "identificacion": {
            "tipoDte": "03",
            "numeroControl": "DTE-03-XYZ-000000000000001",
        },
        "emisor": _sample_emisor(),
        "receptor": _sample_receptor(),
        "cuerpoDocumento": [
            {"descripcion": "Prod", "cantidad": 1, "uniMedida": 59}
        ],
    }
    data = generar_nota_remision_desde_factura(db, factura)
    doc_rel = data["documentoRelacionado"]
    assert doc_rel["tipoDoc"] == "03"
    assert doc_rel["numeroDocumento"] == "DTE-03-XYZ-000000000000001"
    item = data["cuerpoDocumento"][0]
    assert float(item["precioUni"]) == 0.0
    assert float(item["ventaNoSuj"]) == 0.0
    assert float(item["ventaExenta"]) == 0.0
    assert float(item["ventaGravada"]) == 0.0
    assert "-" not in data["emisor"]["nit"]
    assert " " not in data["receptor"]["numDocumento"]


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
    assert data["documentoRelacionado"] is None
    ext = data["extension"]
    assert ext["nombEntrega"] == "Juan"
    assert ext["nombRecibe"] == "Ana"
    assert ext["docuEntrega"] == "06141407100012"
    assert ext["docuRecibe"] == "12345678"
    assert "-" not in data["emisor"]["nit"]
    assert " " not in data["receptor"]["numDocumento"]


def test_nr_item_validation(monkeypatch):
    monkeypatch.setattr("dte._load_datos_negocio", lambda: {"dte_api": {}})
    db = DB(":memory:")
    emisor = _sample_emisor()
    receptor = _sample_receptor()
    with pytest.raises(ValueError):
        generar_nota_remision_independiente(
            db,
            emisor=emisor,
            receptor=receptor,
            detalles=[{"descripcion": "Prod", "cantidad": 0, "uniMedida": 59}],
        )
    with pytest.raises(ValueError):
        generar_nota_remision_independiente(
            db,
            emisor=emisor,
            receptor=receptor,
            detalles=[{"descripcion": "Prod", "cantidad": 1}],
        )
