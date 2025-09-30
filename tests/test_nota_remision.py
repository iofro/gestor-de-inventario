from datetime import datetime

import pytest
import warnings

from db import DB
import nota_remision
from nota_remision_electronica import (
    generar_nota_remision_desde_factura,
    generar_nota_remision_independiente,
)
import dte
from utils.fecha import fecha_emision_hoy_str


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
            "departamento": "06",
            "municipio": "23",
            "complemento": "San Salvador",
        },
    }


def _sample_doc_rel():
    return [
        {
            "tipoDocumento": "03",
            "tipoGeneracion": 2,
            "numeroDocumento": "12345678-ABCD-1234-ABCD-1234567890AB",
            "fechaEmision": "2024-01-01",
        }
    ]


def _registrar_envio_relacionado(
    db: DB,
    *,
    codigo_generacion: str | None = None,
    numero_control: str | None = None,
    estado_ui: str = "Aceptado",
):
    for column, definition in (
        ("codigo_lote", "TEXT"),
        ("codigo_generacion", "TEXT"),
        ("numero_control", "TEXT"),
        ("estado_ui", "TEXT"),
        ("estado_ui_tag", "TEXT"),
    ):
        db.ensure_column("dte_envios", column, definition)
    codigo_val = (codigo_generacion or "").strip().upper() or None
    numero_val = (numero_control or "").strip().upper() or None
    db.cursor.execute(
        """
        INSERT INTO dte_envios (
            venta_id, modo, estado, sello, fecha_hora,
            respuesta, codigo_lote, codigo_generacion, numero_control, estado_ui, estado_ui_tag
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            None,
            None,
            "PROCESADO",
            "",
            datetime.utcnow().isoformat(),
            "",
            None,
            codigo_val,
            numero_val,
            estado_ui,
            "" if estado_ui in {"Aceptado", "Enviado"} else "no_recepcion",
        ),
    )
    db.conn.commit()


def test_nr_desde_factura_documento_relacionado(monkeypatch):
    monkeypatch.setattr("dte._load_datos_negocio", lambda: {"dte_api": {}})
    db = DB(":memory:")
    factura = {
        "identificacion": {
            "tipoDte": "03",
            "codigoGeneracion": "12345678-ABCD-1234-ABCD-1234567890AB",
            "fecEmi": "2024-01-01T08:15:30",
        },
        "emisor": _sample_emisor(),
        "receptor": _sample_receptor(),
        "cuerpoDocumento": [
            {"descripcion": "Prod", "cantidad": 1, "uniMedida": 59}
        ],
    }
    extension = {
        "nombEntrega": "Juan",
        "docuEntrega": "123",
        "nombRecibe": "Ana",
        "docuRecibe": "456",
        "observaciones": "Obs",
    }
    _registrar_envio_relacionado(
        db,
        codigo_generacion="12345678-ABCD-1234-ABCD-1234567890AB",
    )
    data = generar_nota_remision_desde_factura(db, factura, extension=extension)
    doc_rel = data["documentoRelacionado"][0]
    assert doc_rel["tipoDocumento"] == "03"
    assert doc_rel["numeroDocumento"] == "12345678-ABCD-1234-ABCD-1234567890AB"
    assert doc_rel["fechaEmision"] == "2024-01-01"
    assert factura["identificacion"]["fecEmi"] == "2024-01-01T08:15:30"
    today_str = fecha_emision_hoy_str()
    assert data["identificacion"]["fecEmi"] == today_str
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


def test_nr_documento_relacionado_con_numero_control(monkeypatch):
    monkeypatch.setattr("dte._load_datos_negocio", lambda: {"dte_api": {}})
    db = DB(":memory:")
    factura = {
        "identificacion": {
            "tipoDte": "03",
            "numeroControl": "DTE-03-S001P001-000000000000447",
            "fecEmi": "2024-01-01",
        },
        "emisor": _sample_emisor(),
        "receptor": _sample_receptor(),
        "cuerpoDocumento": [
            {"descripcion": "Prod", "cantidad": 1, "uniMedida": 59}
        ],
    }
    extension = {
        "nombEntrega": "Juan",
        "docuEntrega": "123",
        "nombRecibe": "Ana",
        "docuRecibe": "456",
        "observaciones": "Obs",
    }
    _registrar_envio_relacionado(
        db,
        numero_control="DTE-03-S001P001-000000000000447",
        estado_ui="Enviado",
    )
    data = generar_nota_remision_desde_factura(db, factura, extension=extension)
    doc_rel = data["documentoRelacionado"][0]
    assert doc_rel["tipoDocumento"] == "03"
    assert doc_rel["numeroDocumento"] == "DTE-03-S001P001-000000000000447"
    assert doc_rel["tipoGeneracion"] == 1


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
    _registrar_envio_relacionado(
        db,
        codigo_generacion="12345678-ABCD-1234-ABCD-1234567890AB",
    )
    data = generar_nota_remision_desde_factura(
        db, factura, extension=extension
    )
    assert data["extension"]["nombEntrega"] == "Juan"
    rec = data["receptor"]
    assert "nombreComercial" in rec
    assert rec["nombreComercial"] is None


def test_normalizar_documento_relacionado_preserva_prefijo():
    doc_rel = [
        {
            "tipoDocumento": "03",
            "numeroDocumento": "DTE-03-S001P001-000000000000447",
            "fechaEmision": "2024-09-30",
        }
    ]
    normalized = nota_remision._normalizar_documento_relacionado(doc_rel)
    assert normalized[0]["numeroDocumento"] == "DTE-03-S001P001-000000000000447"
    assert normalized[0]["tipoGeneracion"] == 1


def test_normalizar_documento_relacionado_codigo_generacion():
    doc_rel = [
        {
            "tipoDocumento": "03",
            "codigoGeneracion": "a8748223-7cd8-42a3-84b2-c7d2473504dc",
            "fechaEmision": "30/09/2025",
        }
    ]
    normalized = nota_remision._normalizar_documento_relacionado(doc_rel)
    assert normalized[0]["tipoGeneracion"] == 2
    assert (
        normalized[0]["numeroDocumento"]
        == "A8748223-7CD8-42A3-84B2-C7D2473504DC"
    )
    assert (
        normalized[0]["codigoGeneracion"]
        == "A8748223-7CD8-42A3-84B2-C7D2473504DC"
    )
    assert normalized[0]["fechaEmision"] == "2025-09-30"


def test_normalizar_documento_relacionado_tipo_incoherente():
    doc_rel = [
        {
            "tipoDocumento": "01",
            "numeroDocumento": "DTE-03-S001P001-000000000000447",
            "fechaEmision": "2024-09-30",
        }
    ]
    with pytest.raises(ValueError, match="prefijo de numeroDocumento"):
        nota_remision._normalizar_documento_relacionado(doc_rel)


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
                "departamento": "06",
                "municipio": "23",
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
        "observaciones": "Obs",
    }
    _registrar_envio_relacionado(
        db,
        codigo_generacion="12345678-ABCD-1234-ABCD-1234567890AB",
    )
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
    doc_rel = _sample_doc_rel()
    _registrar_envio_relacionado(
        db,
        codigo_generacion=doc_rel[0]["numeroDocumento"],
    )
    data = generar_nota_remision_independiente(
        db,
        emisor=emisor,
        receptor=receptor,
        detalles=detalles,
        documento_relacionado=doc_rel,
        extension=extension,
    )
    assert data["documentoRelacionado"][0]["numeroDocumento"] == doc_rel[0]["numeroDocumento"]
    item = data["cuerpoDocumento"][0]
    assert item["numeroDocumento"] == doc_rel[0]["numeroDocumento"]
    ext = data["extension"]
    assert ext["nombEntrega"] == "Juan"
    assert ext["nombRecibe"] == "Ana"
    assert ext["docuEntrega"] == "06141407100012"
    assert ext["docuRecibe"] == "12345678"
    assert "-" not in data["emisor"]["nit"]
    assert data["emisor"]["tipoEstablecimiento"] == "01"
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
    _registrar_envio_relacionado(
        db,
        codigo_generacion=_sample_doc_rel()[0]["numeroDocumento"],
    )
    with pytest.raises(ValueError):
        generar_nota_remision_independiente(
            db,
            emisor=emisor,
            receptor=receptor,
            detalles=detalles,
            documento_relacionado=_sample_doc_rel(),
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
    _registrar_envio_relacionado(
        db,
        codigo_generacion=_sample_doc_rel()[0]["numeroDocumento"],
    )
    with pytest.raises(ValueError):
        generar_nota_remision_independiente(
            db,
            emisor=emisor,
            receptor=receptor,
            detalles=detalles,
            documento_relacionado=_sample_doc_rel(),
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
        _registrar_envio_relacionado(
            db,
            codigo_generacion=_sample_doc_rel()[0]["numeroDocumento"],
        )
        generar_nota_remision_independiente(
            db,
            emisor=emisor,
            receptor=receptor,
            detalles=[{"descripcion": "Prod", "cantidad": 0, "uniMedida": 59}],
            documento_relacionado=_sample_doc_rel(),
            extension=extension,
        )
    extension = {
        "nombEntrega": "X",
        "docuEntrega": "123",
        "nombRecibe": "Y",
        "docuRecibe": "456",
        "observaciones": "Obs",
    }
    _registrar_envio_relacionado(
        db,
        codigo_generacion=_sample_doc_rel()[0]["numeroDocumento"],
    )
    data = generar_nota_remision_independiente(
        db,
        emisor=emisor,
        receptor=receptor,
        detalles=[{"descripcion": "Prod", "cantidad": 1, "uniMedida": 1}],
        documento_relacionado=_sample_doc_rel(),
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
            "departamento": "06",
            "municipio": "23",
            "complemento": "San Salvador",
        },
    }
    factura = {
        "identificacion": {"tipoDte": "03", "codigoGeneracion": "1", "fecEmi": "2024-01-01"},
        "emisor": emisor,
        "receptor": receptor,
        "cuerpoDocumento": [{"descripcion": "Prod", "cantidad": 1, "uniMedida": 59}],
    }
    extension = {
        "nombEntrega": "Juan",
        "docuEntrega": "123",
        "nombRecibe": "Ana",
        "docuRecibe": "456",
        "observaciones": "Obs",
    }
    _registrar_envio_relacionado(
        db,
        codigo_generacion=factura["identificacion"]["codigoGeneracion"],
    )
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
            "departamento": "06",
            "municipio": "23",
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
    _registrar_envio_relacionado(
        db,
        codigo_generacion=_sample_doc_rel()[0]["numeroDocumento"],
    )
    with pytest.raises(ValueError):
        generar_nota_remision_independiente(
            db,
            emisor=emisor,
            receptor=receptor,
            detalles=detalles,
            documento_relacionado=_sample_doc_rel(),
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
    extension = {
        "nombEntrega": "Juan",
        "docuEntrega": "123",
        "nombRecibe": "Ana",
        "docuRecibe": "456",
        "observaciones": "Obs",
    }
    _registrar_envio_relacionado(
        db,
        codigo_generacion=_sample_doc_rel()[0]["numeroDocumento"],
    )
    with pytest.raises(ValueError, match=f"receptor requiere {campo}"):
        generar_nota_remision_independiente(
            db,
            emisor=emisor,
            receptor=receptor,
            detalles=detalles,
            documento_relacionado=_sample_doc_rel(),
            extension=extension,
        )


def test_receptor_direccion_complemento_faltante(monkeypatch):
    monkeypatch.setattr("dte._load_datos_negocio", lambda: {"dte_api": {}})
    db = DB(":memory:")
    emisor = _sample_emisor()
    receptor = _sample_receptor()
    receptor["direccion"].pop("complemento")
    detalles = [{"descripcion": "Prod", "cantidad": 1, "uniMedida": 59}]
    extension = {
        "nombEntrega": "Juan",
        "docuEntrega": "123",
        "nombRecibe": "Ana",
        "docuRecibe": "456",
        "observaciones": "Obs",
    }
    _registrar_envio_relacionado(
        db,
        codigo_generacion=_sample_doc_rel()[0]["numeroDocumento"],
    )
    with pytest.raises(ValueError, match="receptor requiere direccion.complemento"):
        generar_nota_remision_independiente(
            db,
            emisor=emisor,
            receptor=receptor,
            detalles=detalles,
            documento_relacionado=_sample_doc_rel(),
            extension=extension,
        )


def test_nr_documento_relacionado_rechazado(monkeypatch):
    monkeypatch.setattr("dte._load_datos_negocio", lambda: {"dte_api": {}})
    db = DB(":memory:")
    factura = {
        "identificacion": {
            "tipoDte": "03",
            "numeroControl": "DTE-03-S001P001-000000000000447",
            "fecEmi": "2024-01-01",
        },
        "emisor": _sample_emisor(),
        "receptor": _sample_receptor(),
        "cuerpoDocumento": [
            {"descripcion": "Prod", "cantidad": 1, "uniMedida": 59}
        ],
    }
    extension = {
        "nombEntrega": "Juan",
        "docuEntrega": "123",
        "nombRecibe": "Ana",
        "docuRecibe": "456",
        "observaciones": "Obs",
    }
    _registrar_envio_relacionado(
        db,
        numero_control="DTE-03-S001P001-000000000000447",
        estado_ui="Rechazado",
    )
    with pytest.raises(ValueError, match="aún no ha sido recepcionado por MH"):
        generar_nota_remision_desde_factura(db, factura, extension=extension)


def test_nr_documento_relacionado_inexistente(monkeypatch):
    monkeypatch.setattr("dte._load_datos_negocio", lambda: {"dte_api": {}})
    db = DB(":memory:")
    factura = {
        "identificacion": {
            "tipoDte": "03",
            "numeroControl": "DTE-03-S001P001-000000000000999",
            "fecEmi": "2024-01-01",
        },
        "emisor": _sample_emisor(),
        "receptor": _sample_receptor(),
        "cuerpoDocumento": [
            {"descripcion": "Prod", "cantidad": 1, "uniMedida": 59}
        ],
    }
    extension = {
        "nombEntrega": "Juan",
        "docuEntrega": "123",
        "nombRecibe": "Ana",
        "docuRecibe": "456",
        "observaciones": "Obs",
    }
    with pytest.raises(ValueError, match="sin registro local"):
        generar_nota_remision_desde_factura(db, factura, extension=extension)
