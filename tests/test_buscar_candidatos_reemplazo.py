import json
import uuid

import pytest

import anulacion


def _crear_factura(base_factory, *, tipo="01", ambiente="00", codigo=None, numero=None):
    factura = base_factory()
    factura["identificacion"]["tipoDte"] = tipo
    factura["identificacion"]["ambiente"] = ambiente
    factura["identificacion"]["codigoGeneracion"] = codigo or str(uuid.uuid4()).upper()
    factura["identificacion"]["numeroControl"] = numero or "DTE-01-S001P001-000000000000001"
    factura["resumen"]["montoTotalOperacion"] = "25.50"
    return factura


@pytest.mark.usefixtures("qt_app")
def test_buscar_candidatos_reemplazo_filters(db_conn, tmp_path, dte_metadata_factory):
    factura_a = _crear_factura(
        dte_metadata_factory,
        codigo=str(uuid.uuid4()).upper(),
        numero="DTE-01-S001P001-000000000000111",
    )
    json_a = tmp_path / "candidato_a.json"
    json_a.write_text(json.dumps(factura_a), encoding="utf-8")
    extra = {
        "codigoGeneracion": factura_a["identificacion"]["codigoGeneracion"],
        "numeroControl": factura_a["identificacion"]["numeroControl"],
        "dteJsonPath": str(json_a),
        "selloRecibido": "A" * 40,
    }
    venta_a = db_conn.add_venta("2024-02-01", 25.5, extra=extra)
    db_conn.registrar_envio_dte(
        venta_a,
        "manual",
        "Aceptada",
        "A" * 40,
        respuesta_json=json.dumps({"documento": factura_a}),
        codigo_generacion=factura_a["identificacion"]["codigoGeneracion"],
        numero_control=factura_a["identificacion"]["numeroControl"],
    )
    row_a = db_conn.cursor.lastrowid
    db_conn.ensure_column("dte_envios", "ambiente", "TEXT")
    db_conn.cursor.execute(
        "UPDATE dte_envios SET ambiente=? WHERE id=?",
        (factura_a["identificacion"]["ambiente"], row_a),
    )

    codigo_b = str(uuid.uuid4()).upper()
    respuesta_b = {
        "documento": {
            "identificacion": {"fecEmi": "2024-02-05"},
            "receptor": factura_a["receptor"],
        }
    }
    db_conn.registrar_envio_dte(
        None,
        "manual",
        "Recibida",
        "B" * 40,
        respuesta_json=json.dumps(respuesta_b),
        codigo_generacion=codigo_b,
        numero_control="DTE-01-S001P001-000000000000222",
    )
    row_b = db_conn.cursor.lastrowid
    db_conn.cursor.execute(
        "UPDATE dte_envios SET ambiente=? WHERE id=?",
        (factura_a["identificacion"]["ambiente"], row_b),
    )

    codigo_d = str(uuid.uuid4()).upper()
    factura_d = _crear_factura(
        dte_metadata_factory,
        codigo=codigo_d,
        numero="DTE-01-S001P001-000000000000444",
        ambiente=factura_a["identificacion"]["ambiente"],
    )
    factura_d["receptor"] = factura_a["receptor"]
    db_conn.registrar_envio_dte(
        None,
        "manual",
        "En proceso",
        "D" * 40,
        respuesta_json=json.dumps({"documento": factura_d}),
        codigo_generacion=codigo_d,
        numero_control=factura_d["identificacion"]["numeroControl"],
    )
    row_d = db_conn.cursor.lastrowid
    db_conn.cursor.execute(
        "UPDATE dte_envios SET ambiente=? WHERE id=?",
        (factura_a["identificacion"]["ambiente"], row_d),
    )

    factura_c = _crear_factura(
        dte_metadata_factory,
        tipo="03",
        codigo=str(uuid.uuid4()).upper(),
        numero="DTE-03-S001P001-000000000000333",
    )
    json_c = tmp_path / "candidato_c.json"
    json_c.write_text(json.dumps(factura_c), encoding="utf-8")
    extra_c = {
        "codigoGeneracion": factura_c["identificacion"]["codigoGeneracion"],
        "numeroControl": factura_c["identificacion"]["numeroControl"],
        "dteJsonPath": str(json_c),
        "selloRecibido": "C" * 40,
    }
    venta_c = db_conn.add_venta("2024-02-02", 10, extra=extra_c)
    db_conn.registrar_envio_dte(
        venta_c,
        "manual",
        "Aceptado",
        "C" * 40,
        respuesta_json=json.dumps({"documento": factura_c}),
        codigo_generacion=factura_c["identificacion"]["codigoGeneracion"],
        numero_control=factura_c["identificacion"]["numeroControl"],
    )
    row_c = db_conn.cursor.lastrowid
    db_conn.cursor.execute(
        "UPDATE dte_envios SET ambiente=? WHERE id=?",
        (factura_c["identificacion"]["ambiente"], row_c),
    )
    db_conn.conn.commit()

    receptor_doc = factura_a["receptor"]["numDocumento"]
    filtros = {
        "tipo_dte": "01",
        "ambiente": factura_a["identificacion"]["ambiente"],
        "exclude_uuid": "IGNORAR",
        "recepcionado": True,
        "mismo_receptor": True,
        "receptor_documentos": [receptor_doc],
    }
    resultados = anulacion.buscar_candidatos_reemplazo(db_conn, filtros)
    codigos = {r["codigo_generacion"] for r in resultados}

    assert factura_a["identificacion"]["codigoGeneracion"] in codigos
    assert codigo_b in codigos
    assert factura_c["identificacion"]["codigoGeneracion"] not in codigos
    assert codigo_d not in codigos

    datos = {item["codigo_generacion"]: item for item in resultados}
    cand_a = datos[factura_a["identificacion"]["codigoGeneracion"]]
    assert cand_a["tipo_dte"] == "01"
    assert cand_a["seleccionable"] is True
    assert cand_a["preselect"] is True
    assert pytest.approx(cand_a["total"], rel=1e-6) == 25.5
    assert cand_a["emisor_documento"] == factura_a["emisor"]["nit"]

    cand_b = datos[codigo_b]
    assert cand_b["tipo_indeterminado"] is True
    assert cand_b["seleccionable"] is False

    filtros_con_exclusion = dict(filtros)
    filtros_con_exclusion["exclude_uuid"] = factura_a["identificacion"]["codigoGeneracion"]
    excluidos = anulacion.buscar_candidatos_reemplazo(db_conn, filtros_con_exclusion)
    codigos_excluidos = {r["codigo_generacion"] for r in excluidos}
    assert factura_a["identificacion"]["codigoGeneracion"] not in codigos_excluidos
    assert codigo_b in codigos_excluidos

    filtros_busqueda = dict(filtros)
    filtros_busqueda["search"] = receptor_doc
    resultados_busqueda = anulacion.buscar_candidatos_reemplazo(db_conn, filtros_busqueda)
    assert {r["codigo_generacion"] for r in resultados_busqueda} == codigos

    filtros_sin_recepcionado = dict(filtros)
    filtros_sin_recepcionado.pop("recepcionado", None)
    sin_filtro = anulacion.buscar_candidatos_reemplazo(db_conn, filtros_sin_recepcionado)
    codigos_sin_filtro = {r["codigo_generacion"] for r in sin_filtro}
    assert codigo_d in codigos_sin_filtro


@pytest.mark.parametrize("metadata_source", ["payload", "respuesta"])
def test_buscar_candidatos_reemplazo_recupera_codigo_de_metadatos(
    monkeypatch, dte_metadata_factory, metadata_source
):
    codigo_generacion = str(uuid.uuid4()).upper()
    factura = _crear_factura(
        dte_metadata_factory,
        codigo=codigo_generacion,
        numero="DTE-01-S001P001-000000000000555",
    )

    class DummyCursor:
        def __init__(self, rows):
            self._rows = rows
            self._current_rows = []

        def execute(self, query, params=None):
            query_text = str(query or "").strip().lower()
            if query_text.startswith("select"):
                self._current_rows = self._rows
            else:
                self._current_rows = []
            return self

        def fetchall(self):
            return self._current_rows

    class DummyDB:
        def __init__(self, rows):
            self.cursor = DummyCursor(rows)

        def ensure_column(self, *args, **kwargs):
            return None

    rows = [
        {
            "id": 1,
            "venta_id": 10,
            "fecha_hora": "2024-02-03T10:00:00",
            "modo": "manual",
            "estado": "Aceptado",
            "sello": "A" * 40,
            "codigo_generacion": None,
            "numero_control": None,
            "respuesta": "{}",
            "ambiente": None,
        }
    ]
    dummy_db = DummyDB(rows)

    payload = factura if metadata_source == "payload" else None
    respuesta_doc = factura if metadata_source == "respuesta" else None

    monkeypatch.setattr(anulacion, "_load_dte_json_from_venta", lambda *_: payload)
    monkeypatch.setattr(anulacion, "_parse_respuesta_documento", lambda *_: respuesta_doc)

    resultados = anulacion.buscar_candidatos_reemplazo(dummy_db, {})

    assert len(resultados) == 1
    candidato = resultados[0]
    assert candidato["codigo_generacion"] == codigo_generacion
    assert candidato["numero_control"] == factura["identificacion"]["numeroControl"]
    assert candidato["seleccionable"] is True
