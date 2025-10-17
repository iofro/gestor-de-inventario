from __future__ import annotations

import json
import logging

import pytest

from declaracion import dte_provider


def test_tipo_dte_detects_sources_and_aliases():
    assert dte_provider._tipo_dte({"dte_json": {"identificacion": {"tipoDte": "03"}}}) == "03"

    row_dte = {"dte_json": {"identificacion": {}, "tipoDte": "03"}}
    assert dte_provider._tipo_dte(row_dte) == "03"

    row_extra = {"dte_json": {"identificacion": {}}, "extra_data": {"tipoDocumento": "3"}}
    assert dte_provider._tipo_dte(row_extra) == "03"

    row_alias = {"dte_json": {"identificacion": {}}, "extra_data": {"tipo_hint": "CCF"}}
    assert dte_provider._tipo_dte(row_alias) == "03"


def test_clase_por_tipo_catalogo():
    for code in dte_provider.CAT002_VALID:
        assert dte_provider.CLASE_POR_TIPO[code] == "4"


def _dte_payload(
    *,
    tipo: str,
    fecha: str,
    codigo: str,
    numero_control: str,
    nombre: str,
    receptor: dict,
    resumen: dict,
    tipo_operacion: int = 1,
    tipo_modelo: int = 1,
    sello: str | None = None,
) -> dict:
    payload = {
        "dteJson": {
            "identificacion": {
                "tipoDte": tipo,
                "fecEmi": fecha,
                "codigoGeneracion": codigo,
                "numeroControl": numero_control,
                "tipoOperacion": tipo_operacion,
                "tipoModelo": tipo_modelo,
            },
            "receptor": {"nombre": nombre, **receptor},
            "resumen": resumen,
        },
        "codigoGeneracion": codigo,
        "numeroControl": numero_control,
        "dteJsonPath": f"/tmp/{codigo or 'sin'}.json",
    }
    if sello:
        payload["selloRecibido"] = sello
    return payload


def _insert_envio(
    db_conn,
    venta_id: int,
    *,
    codigo: str | None,
    numero: str | None,
    estado: str,
    tag: str,
    manual: int,
    respuesta_extra: dict | None = None,
) -> None:
    db_conn.ensure_column("dte_envios", "codigo_generacion", "TEXT")
    db_conn.ensure_column("dte_envios", "numero_control", "TEXT")
    db_conn.ensure_column("dte_envios", "estado_ui", "TEXT")
    db_conn.ensure_column("dte_envios", "estado_ui_tag", "TEXT")
    db_conn.ensure_column("dte_envios", "estado_ui_manual", "INTEGER DEFAULT 0")
    respuesta = {"estado": estado, "codigoGeneracion": codigo, "numeroControl": numero}
    if respuesta_extra:
        respuesta.update(respuesta_extra)
    db_conn.cursor.execute(
        """
        INSERT INTO dte_envios (
            venta_id, codigo_generacion, numero_control, estado_ui, estado_ui_tag, estado_ui_manual, respuesta
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            venta_id,
            codigo,
            numero,
            estado,
            tag,
            manual,
            json.dumps(respuesta),
        ),
    )


@pytest.mark.usefixtures("db_conn")
def test_build_anexo_records_filters_and_dedup(db_conn, caplog):
    caplog.set_level(logging.INFO, logger="declaracion.dte_provider")

    cliente_emp = db_conn.add_cliente(
        nombre="Empresa Uno",
        nrc="123456-7",
        nit="0614-199001-101-9",
        dui="",
        giro="",
        telefono="",
        email="",
        direccion="San Salvador",
        departamento="06",
        municipio="23",
    )
    cliente_nat = db_conn.add_cliente(
        nombre="Persona Natural",
        nrc="",
        nit="",
        dui="01234567-8",
        giro="",
        telefono="",
        email="",
        direccion="San Salvador",
        departamento="06",
        municipio="23",
    )

    resumen_cf = {
        "totalExenta": "0.00",
        "totalNoSuj": "0.00",
        "totalGravada": "100.00",
        "totalIva": "13.00",
        "totalPagar": "113.00",
    }

    venta_cf = db_conn.add_venta(
        "2024-01-15",
        113,
        cliente_id=cliente_emp,
        extra=_dte_payload(
            tipo="03",
            fecha="2024-01-15",
            codigo="CF-001",
            numero_control="DTE-03-0001",
            nombre="Empresa Uno",
            receptor={"nit": "06141990011019", "nrc": "1234567", "tipoDocumento": "36", "numDocumento": "06141990011019"},
            resumen=resumen_cf,
        ),
    )
    _insert_envio(
        db_conn,
        venta_cf,
        codigo="CF-001",
        numero="DTE-03-0001",
        estado="Recibido",
        tag="recibido",
        manual=0,
        respuesta_extra={"selloRecibido": "SELLO-RESP"},
    )

    resumen_nd = {
        "totalExenta": "5.00",
        "totalNoSuj": "0.00",
        "totalGravada": "0.00",
        "totalPagar": "5.00",
    }
    venta_nd = db_conn.add_venta(
        "2024-01-20",
        5,
        cliente_id=cliente_nat,
        extra=_dte_payload(
            tipo="05",
            fecha="2024/01/20",
            codigo="ND-001",
            numero_control="DTE-05-0001",
            nombre="Persona Natural",
            receptor={"dui": "01234567-8", "tipoDocumento": "13", "numDocumento": "01234567-8"},
            resumen=resumen_nd,
        ),
    )
    _insert_envio(db_conn, venta_nd, codigo="ND-001", numero="DTE-05-0001", estado="Aceptada", tag="aceptada", manual=0)

    resumen_nc = {
        "totalExenta": "0.00",
        "totalNoSuj": "2.00",
        "totalGravada": "3.00",
        "totalIva": "0.00",
        "totalPagar": "5.50",
        "tributos": [{"codigo": "20", "valor": "0.50"}],
    }
    venta_nc = db_conn.add_venta(
        "2024-01-21",
        5,
        cliente_id=cliente_emp,
        extra=_dte_payload(
            tipo="06",
            fecha="21/01/2024",
            codigo="NC-001",
            numero_control="DTE-06-0001",
            nombre="Empresa Uno",
            receptor={"nit": "06141990011019", "nrc": "1234567", "tipoDocumento": "36", "numDocumento": "06141990011019"},
            resumen=resumen_nc,
        ),
    )
    _insert_envio(
        db_conn,
        venta_nc,
        codigo="NC-001",
        numero="DTE-06-0001",
        estado="Aceptado",
        tag="rechazado",
        manual=1,
    )

    resumen_sin_ctrl = {
        "totalExenta": "0.00",
        "totalNoSuj": "0.00",
        "totalGravada": "50.00",
        "totalIva": "6.50",
        "totalPagar": "56.50",
    }
    venta_sin_ctrl = db_conn.add_venta(
        "2024-01-24",
        56,
        cliente_id=cliente_emp,
        extra=_dte_payload(
            tipo="03",
            fecha="24/01/2024",
            codigo="CF-002",
            numero_control="",
            nombre="Empresa Uno",
            receptor={"nit": "06141990011019", "nrc": "1234567"},
            resumen=resumen_sin_ctrl,
        ),
    )
    _insert_envio(db_conn, venta_sin_ctrl, codigo="CF-002", numero=None, estado="Enviado", tag="enviado", manual=0)

    resumen_cf_consumidor = {
        "totalExenta": "0.00",
        "totalNoSuj": "0.00",
        "totalGravada": "20.00",
        "totalPagar": "20.50",
    }
    venta_cf_cons = db_conn.add_venta(
        "2024-01-22",
        20,
        cliente_id=cliente_nat,
        extra=_dte_payload(
            tipo="01",
            fecha="2024-01-22",
            codigo="CFII-001",
            numero_control="DTE-01-0001",
            nombre="Persona Natural",
            receptor={"dui": "01234567-8", "tipoDocumento": "13", "numDocumento": "01234567-8"},
            resumen=resumen_cf_consumidor,
        ),
    )
    _insert_envio(db_conn, venta_cf_cons, codigo="CFII-001", numero="DTE-01-0001", estado="Procesado", tag="procesado", manual=0)

    resumen_cf_extra = {
        "totalExenta": "0.00",
        "totalNoSuj": "0.00",
        "totalGravada": "10.00",
        "totalPagar": "10.00",
    }
    venta_cf_extra = db_conn.add_venta(
        "2024-01-22",
        10,
        cliente_id=cliente_nat,
        extra=_dte_payload(
            tipo="01",
            fecha="2024-01-22",
            codigo="CFII-005",
            numero_control="DTE-01-0003",
            nombre="Persona Natural",
            receptor={"dui": "01234567-8", "tipoDocumento": "13", "numDocumento": "01234567-8"},
            resumen=resumen_cf_extra,
        ),
    )
    _insert_envio(db_conn, venta_cf_extra, codigo="CFII-005", numero="DTE-01-0003", estado="Recibido", tag="recibido", manual=0)

    resumen_fc = {
        "totalExenta": "1.00",
        "totalNoSuj": "2.00",
        "totalGravada": "3.00",
        "totalPagar": "6.50",
    }
    venta_fc = db_conn.add_venta(
        "2024-01-23",
        6,
        cliente_id=cliente_emp,
        extra=_dte_payload(
            tipo="02",
            fecha="2024-01-23",
            codigo="CFII-002",
            numero_control="DTE-02-0001",
            nombre="Empresa Uno",
            receptor={"nit": "06141990011019", "nrc": "1234567"},
            resumen=resumen_fc,
        ),
    )
    _insert_envio(db_conn, venta_fc, codigo="CFII-002", numero="DTE-02-0001", estado="Pendiente", tag="pendiente", manual=0)

    resumen_manual = {
        "totalExenta": "0.00",
        "totalNoSuj": "0.00",
        "totalGravada": "7.00",
        "totalPagar": "7.00",
    }
    venta_manual = db_conn.add_venta(
        "2024-01-24",
        7,
        cliente_id=cliente_emp,
        extra=_dte_payload(
            tipo="01",
            fecha="2024/01/24",
            codigo="CFII-003",
            numero_control="DTE-01-0002",
            nombre="Empresa Uno",
            receptor={"nit": "06141990011019", "tipoDocumento": "36", "numDocumento": "06141990011019"},
            resumen=resumen_manual,
        ),
    )
    _insert_envio(
        db_conn,
        venta_manual,
        codigo="CFII-003",
        numero="DTE-01-0002",
        estado="Aceptado",
        tag="rechazado",
        manual=1,
    )

    resumen_no_cf = {
        "totalExenta": "0.00",
        "totalNoSuj": "0.00",
        "totalGravada": "12.00",
        "totalPagar": "12.00",
    }
    venta_no_cf = db_conn.add_venta(
        "2024-01-27",
        12,
        cliente_id=cliente_emp,
        extra=_dte_payload(
            tipo="11",
            fecha="2024-01-27",
            codigo="CFII-004",
            numero_control="DTE-11-0001",
            nombre="Empresa Uno",
            receptor={"nit": "06141990011019", "nrc": "1234567"},
            resumen=resumen_no_cf,
        ),
    )
    _insert_envio(
        db_conn,
        venta_no_cf,
        codigo="CFII-004",
        numero="DTE-11-0001",
        estado="Aceptado",
        tag="aceptado",
        manual=0,
    )

    venta_cf_dup = db_conn.add_venta(
        "2024-01-26",
        20,
        cliente_id=cliente_nat,
        extra=_dte_payload(
            tipo="01",
            fecha="2024-01-26",
            codigo="CFII-001",
            numero_control="DTE-01-9999",
            nombre="Persona Natural",
            receptor={"dui": "01234567-8"},
            resumen=resumen_cf_consumidor,
        ),
    )
    _insert_envio(db_conn, venta_cf_dup, codigo="CFII-001", numero="DTE-01-9999", estado="Aceptado", tag="aceptado", manual=0)

    venta_sin_codigo = db_conn.add_venta(
        "2024-01-25",
        5,
        cliente_id=cliente_emp,
        extra=_dte_payload(
            tipo="03",
            fecha="2024-01-25",
            codigo="",
            numero_control="",
            nombre="Empresa Uno",
            receptor={"nit": "06141990011019", "nrc": "1234567"},
            resumen=resumen_cf,
        ),
    )
    _insert_envio(db_conn, venta_sin_codigo, codigo=None, numero=None, estado="Enviado", tag="enviado", manual=0)

    venta_otro_periodo = db_conn.add_venta(
        "2023-12-15",
        5,
        cliente_id=cliente_emp,
        extra=_dte_payload(
            tipo="03",
            fecha="2023-12-15",
            codigo="OLD-001",
            numero_control="DTE-03-OLD",
            nombre="Empresa Uno",
            receptor={"nit": "06141990011019", "nrc": "1234567"},
            resumen=resumen_cf,
        ),
    )
    _insert_envio(db_conn, venta_otro_periodo, codigo="OLD-001", numero="DTE-03-OLD", estado="Enviado", tag="enviado", manual=0)

    rows = dte_provider.get_facturacion_rows(db_conn, "202401")
    codigos_rows = {row.get("codigo_generacion") for row in rows if row.get("codigo_generacion")}
    assert "OLD-001" not in codigos_rows
    assert any(row.get("sello_recepcion") == "SELLO-RESP" for row in rows if row.get("codigo_generacion") == "CF-001")

    contribuyentes = dte_provider.build_anexo_i_records(rows, db_conn)
    cf = dte_provider.build_anexo_ii_records(rows, db_conn)

    codigos_contri = {r.codigo_generacion for r in contribuyentes}
    assert codigos_contri == {"CF-001", "ND-001", "NC-001", "CF-002"}
    sin_ctrl = next(r for r in contribuyentes if r.codigo_generacion == "CF-002")
    assert sin_ctrl.numero_control is None

    nc = next(r for r in contribuyentes if r.codigo_generacion == "NC-001")
    assert nc.debito_fiscal == "0.50"
    assert nc.estado_manual == "Aceptado"
    assert nc.estado == "rechazado"

    cf_by_fecha = {r.fecha: r for r in cf}
    assert set(cf_by_fecha) == {"22/01/2024", "24/01/2024"}
    assert all(r.codigo_generacion != "CFII-004" for r in cf)
    cf_manual = cf_by_fecha["24/01/2024"]
    assert cf_manual.estado_manual == "Aceptado"
    assert cf_manual.numero_control == "DTE-01-0002"
    assert cf_manual.clase == "4"

    cf_total = cf_by_fecha["22/01/2024"]
    assert cf_total.numero_doc_del == "CFII-001"
    assert cf_total.numero_doc_al == "CFII-005"
    assert cf_total.ctrl_interno_del == "DTE-01-0001"
    assert cf_total.ctrl_interno_al == "DTE-01-0003"
    assert cf_total.ventas_gravadas_locales == "30.50"
    assert cf_total.total_ventas == "30.50"
    assert cf_total.codigo_generacion == "CFII-005"
    assert cf_total.numero_control == "DTE-01-0003"
    assert cf_total.clase == "4"

    assert any("Anexo I - descartados_sin_codigo" in rec.message for rec in caplog.records)
    assert any("Anexo II - descartados_duplicado" in rec.message for rec in caplog.records)
    assert any("Facturación 202401 - descartados_fuera_de_periodo" in rec.message for rec in caplog.records)


def test_estado_normalizacion_y_apto():
    assert dte_provider.normalize_estado("Procesamiento") == "recibido"
    assert dte_provider.estado_apto("Cancelada") is False
    assert dte_provider.estado_apto("rechazado", override_manual="Aceptada") is True
    assert dte_provider.estado_apto("Procesado") is True
