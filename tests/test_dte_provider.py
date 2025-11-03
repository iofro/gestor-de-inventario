from __future__ import annotations

import json
import logging

from datetime import datetime

import pytest

from declaracion import dte_provider
from utils.facturacion_records import TIPO_DTE_DESC


def _lookup_envio_state(db_conn, venta_id: int) -> str:
    try:
        row = db_conn.cursor.execute(
            """
            SELECT estado_ui, estado_ui_tag, estado
            FROM dte_envios
            WHERE venta_id=?
            ORDER BY estado_ui_manual DESC, id DESC
            LIMIT 1
            """,
            (venta_id,),
        ).fetchone()
    except Exception:
        row = None

    if not row:
        return "Pendiente de envío"

    for key in ("estado_ui", "estado_ui_tag", "estado"):
        value = row[key]
        if isinstance(value, str) and value.strip():
            return value
    return "Pendiente de envío"


def _build_facturacion_rows(db_conn, venta_ids: list[int]) -> list[dict]:
    rows: list[dict] = []
    for venta_id in venta_ids:
        try:
            venta = db_conn.get_venta_by_id(venta_id)
        except Exception:
            venta = None
        if not isinstance(venta, dict):
            continue

        extra_raw = venta.get("extra")
        if isinstance(extra_raw, str) and extra_raw.strip():
            try:
                extra_data = json.loads(extra_raw)
            except Exception:
                extra_data = {}
        elif isinstance(extra_raw, dict):
            extra_data = dict(extra_raw)
        else:
            extra_data = {}

        dte_json = (
            extra_data.get("dteJson")
            or extra_data.get("dte_json")
            or extra_data.get("dte_json_dict")
            or {}
        )
        if not isinstance(dte_json, dict):
            dte_json = {}

        ident = dte_json.get("identificacion") or {}
        receptor = dte_json.get("receptor") or {}

        fecha_val = ident.get("fecEmi") or venta.get("fecha") or ""
        fecha_text = str(fecha_val).strip()
        fecha_obj = None
        if fecha_text:
            for fmt in (
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d %H:%M",
                "%Y-%m-%d",
                "%Y/%m/%d %H:%M:%S",
                "%Y/%m/%d %H:%M",
                "%Y/%m/%d",
                "%d/%m/%Y",
                "%d-%m-%Y",
            ):
                try:
                    fecha_obj = datetime.strptime(fecha_text, fmt)
                    break
                except ValueError:
                    continue
        fecha_norm = fecha_obj.strftime("%Y-%m-%d") if fecha_obj else fecha_text.replace("/", "-")

        tipo_raw = ident.get("tipoDte")
        tipo_code: str | None = None
        if isinstance(tipo_raw, int):
            tipo_code = f"{tipo_raw:02d}"
        elif isinstance(tipo_raw, str):
            tipo_clean = tipo_raw.strip()
            if tipo_clean.isdigit():
                tipo_code = tipo_clean.zfill(2)
            elif tipo_clean:
                tipo_code = tipo_clean

        row = {
            "row_type": "venta",
            "venta_id": venta_id,
            "name": ident.get("numeroControl")
            or ident.get("codigoGeneracion")
            or f"venta_{venta_id}",
            "numero_control": ident.get("numeroControl"),
            "codigo_generacion": ident.get("codigoGeneracion"),
            "fecha": fecha_obj.strftime("%Y-%m-%d") if fecha_obj else fecha_norm,
            "_parsed_fecha": fecha_obj,
            "cliente": receptor.get("nombre") or venta.get("cliente_nombre") or "",
            "cliente_id": venta.get("cliente_id"),
            "vendedor_id": venta.get("vendedor_id"),
            "total": venta.get("total"),
            "estado": "Completa",
            "envio": _lookup_envio_state(db_conn, venta_id),
            "tipo": TIPO_DTE_DESC.get(tipo_code, tipo_code),
            "codigo": tipo_code,
        }
        rows.append(row)
    return rows


def test_tipo_dte_detects_sources_and_aliases():
    assert dte_provider._tipo_dte({"dte_json": {"identificacion": {"tipoDte": "03"}}}) == "03"

    row_dte = {"dte_json": {"identificacion": {}, "tipoDte": "03"}}
    assert dte_provider._tipo_dte(row_dte) == "03"

    row_extra = {"dte_json": {"identificacion": {}}, "extra_data": {"tipoDocumento": "3"}}
    assert dte_provider._tipo_dte(row_extra) == "03"

    row_alias = {"dte_json": {"identificacion": {}}, "extra_data": {"tipo_hint": "CCF"}}
    assert dte_provider._tipo_dte(row_alias) == "03"

    row_snake = {"extra_data": {"tipo_dte": "3"}}
    assert dte_provider._tipo_dte(row_snake) == "03"

    row_numero_control = {"numero_control": "DTE-01-S001P001-000000000000001"}
    assert dte_provider._tipo_dte(row_numero_control) == "01"

    row_json_path = {"json_path": "/tmp/20240101_cliente_Ticket.json"}
    assert dte_provider._tipo_dte(row_json_path) == "01"

    row_path_segment = {"json_path": "C:/Vertex/ccf/documento.json"}
    assert dte_provider._tipo_dte(row_path_segment) == "03"


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
def test_build_anexo_records_filters_and_dedup(db_conn, caplog, monkeypatch):
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

    venta_ids: list[int] = []
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
    venta_ids.append(venta_cf)
    _insert_envio(
        db_conn,
        venta_cf,
        codigo="CF-001",
        numero="DTE-03-0001",
        estado="Enviado",
        tag="enviado",
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
    _insert_envio(db_conn, venta_nd, codigo="ND-001", numero="DTE-05-0001", estado="Enviado", tag="enviado", manual=0)
    venta_ids.append(venta_nd)

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
    venta_ids.append(venta_nc)
    _insert_envio(
        db_conn,
        venta_nc,
        codigo="NC-001",
        numero="DTE-06-0001",
        estado="Enviado",
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
    venta_ids.append(venta_sin_ctrl)
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
    venta_ids.append(venta_cf_cons)

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
    _insert_envio(db_conn, venta_cf_extra, codigo="CFII-005", numero="DTE-01-0003", estado="Enviado", tag="enviado", manual=0)
    venta_ids.append(venta_cf_extra)

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
    _insert_envio(db_conn, venta_fc, codigo="CFII-002", numero="DTE-02-0001", estado="Enviado", tag="enviado", manual=0)
    venta_ids.append(venta_fc)

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
        estado="Enviado",
        tag="rechazado",
        manual=1,
    )
    venta_ids.append(venta_manual)

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
        estado="Enviado",
        tag="enviado",
        manual=0,
    )
    venta_ids.append(venta_no_cf)

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
    _insert_envio(db_conn, venta_cf_dup, codigo="CFII-001", numero="DTE-01-9999", estado="Enviado", tag="enviado", manual=0)
    venta_ids.append(venta_cf_dup)

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
    venta_ids.append(venta_sin_codigo)

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
    venta_ids.append(venta_otro_periodo)

    monkeypatch.setattr(
        dte_provider,
        "_facturacion_rows",
        lambda db: _build_facturacion_rows(db_conn, venta_ids),
    )

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
    assert nc.estado_manual == "Enviado"
    assert nc.estado == "rechazado"

    cf_by_fecha = {r.fecha: r for r in cf}
    assert set(cf_by_fecha) == {"22/01/2024", "23/01/2024", "24/01/2024", "26/01/2024", "27/01/2024"}

    cf_tipo11 = cf_by_fecha["27/01/2024"]
    assert cf_tipo11.tipo == "11"
    assert cf_tipo11.codigo_generacion == "CFII-004"
    assert cf_tipo11.ventas_gravadas_locales == "12.00"
    assert cf_tipo11.total_ventas == "12.00"
    cf_manual = cf_by_fecha["24/01/2024"]
    assert cf_manual.estado_manual == "Enviado"
    assert cf_manual.numero_control == "DTE-01-0002"
    assert cf_manual.clase == "4"

    cf_dup = cf_by_fecha["26/01/2024"]
    assert cf_dup.codigo_generacion == "CFII-001"
    assert cf_dup.numero_control == "DTE-01-9999"

    cf_tipo02 = cf_by_fecha["23/01/2024"]
    assert cf_tipo02.tipo == "02"
    assert cf_tipo02.codigo_generacion == "CFII-002"
    assert cf_tipo02.total_ventas == "6.50"

    cf_total = cf_by_fecha["22/01/2024"]
    assert cf_total.numero_doc_del == "CFII-005"
    assert cf_total.numero_doc_al == "CFII-005"
    assert cf_total.ctrl_interno_del == "DTE-01-0003"
    assert cf_total.ctrl_interno_al == "DTE-01-0003"
    assert cf_total.ventas_gravadas_locales == "10.00"
    assert cf_total.total_ventas == "10.00"
    assert cf_total.codigo_generacion == "CFII-005"
    assert cf_total.numero_control == "DTE-01-0003"
    assert cf_total.clase == "4"

    assert any("Anexo I - descartados_sin_codigo" in rec.message for rec in caplog.records)
    assert any("Anexo II - descartados_no_enviado" in rec.message for rec in caplog.records)
    assert any("Facturación 202401 - descartados_fuera_de_periodo" in rec.message for rec in caplog.records)


@pytest.mark.usefixtures("db_conn")
def test_declaracion_preview_counts_and_exclusions(db_conn, monkeypatch):
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

    resumen_base = {
        "totalExenta": "0.00",
        "totalNoSuj": "0.00",
        "totalGravada": "100.00",
        "totalIva": "13.00",
        "totalPagar": "113.00",
    }

    venta_ids: list[int] = []

    venta_cf = db_conn.add_venta(
        "2024-01-05",
        113,
        cliente_id=cliente_emp,
        extra=_dte_payload(
            tipo="03",
            fecha="2024-01-05",
            codigo="CF-001",
            numero_control="03-0001",
            nombre="Empresa Uno",
            receptor={"nit": "06141990011019", "nrc": "1234567"},
            resumen=resumen_base,
        ),
    )
    _insert_envio(db_conn, venta_cf, codigo="CF-001", numero="03-0001", estado="Enviado", tag="enviado", manual=0)
    venta_ids.append(venta_cf)

    venta_override = db_conn.add_venta(
        "2024-01-06",
        80,
        cliente_id=cliente_emp,
        extra=_dte_payload(
            tipo="03",
            fecha="2024-01-06",
            codigo="OVR-001",
            numero_control="03-0002",
            nombre="Empresa Uno",
            receptor={"nit": "06141990011019", "nrc": "1234567"},
            resumen=resumen_base,
        ),
    )
    _insert_envio(db_conn, venta_override, codigo="OVR-001", numero="03-0002", estado="Enviado", tag="pendiente", manual=1)
    venta_ids.append(venta_override)

    venta_nd = db_conn.add_venta(
        "2024-01-07",
        50,
        cliente_id=cliente_emp,
        extra=_dte_payload(
            tipo="05",
            fecha="2024-01-07",
            codigo="ND-001",
            numero_control="05-0001",
            nombre="Empresa Uno",
            receptor={"nit": "06141990011019", "nrc": "1234567"},
            resumen={
                "totalExenta": "0.00",
                "totalNoSuj": "0.00",
                "totalGravada": "50.00",
                "totalIva": "6.50",
                "totalPagar": "56.50",
            },
        ),
    )
    _insert_envio(db_conn, venta_nd, codigo="ND-001", numero="05-0001", estado="Enviado", tag="enviado", manual=0)
    venta_ids.append(venta_nd)

    venta_nc = db_conn.add_venta(
        "2024-01-08",
        25,
        cliente_id=cliente_emp,
        extra=_dte_payload(
            tipo="06",
            fecha="2024-01-08",
            codigo="NC-001",
            numero_control="06-0001",
            nombre="Empresa Uno",
            receptor={"nit": "06141990011019", "nrc": "1234567"},
            resumen={
                "totalExenta": "0.00",
                "totalNoSuj": "5.00",
                "totalGravada": "0.00",
                "totalIva": "0.00",
                "totalPagar": "5.50",
                "tributos": [{"codigo": "20", "valor": "0.50"}],
            },
        ),
    )
    _insert_envio(db_conn, venta_nc, codigo="NC-001", numero="06-0001", estado="Enviado", tag="enviado", manual=0)
    venta_ids.append(venta_nc)

    venta_pending = db_conn.add_venta(
        "2024-01-09",
        60,
        cliente_id=cliente_emp,
        extra=_dte_payload(
            tipo="03",
            fecha="2024-01-09",
            codigo="PEN-001",
            numero_control="03-0003",
            nombre="Empresa Uno",
            receptor={"nit": "06141990011019", "nrc": "1234567"},
            resumen=resumen_base,
        ),
    )
    _insert_envio(db_conn, venta_pending, codigo="PEN-001", numero="03-0003", estado="Pendiente", tag="pendiente", manual=0)
    venta_ids.append(venta_pending)

    venta_dup = db_conn.add_venta(
        "2024-01-10",
        40,
        cliente_id=cliente_emp,
        extra=_dte_payload(
            tipo="05",
            fecha="2024-01-10",
            codigo="ND-001",
            numero_control="05-0002",
            nombre="Empresa Uno",
            receptor={"nit": "06141990011019", "nrc": "1234567"},
            resumen=resumen_base,
        ),
    )
    _insert_envio(db_conn, venta_dup, codigo="ND-001", numero="05-0002", estado="Enviado", tag="enviado", manual=0)
    venta_ids.append(venta_dup)

    payload_sin_codigo = _dte_payload(
        tipo="03",
        fecha="2024-01-11",
        codigo="SC-001",
        numero_control="03-0004",
        nombre="Empresa Uno",
        receptor={"nit": "06141990011019", "nrc": "1234567"},
        resumen=resumen_base,
    )
    payload_sin_codigo.pop("codigoGeneracion", None)
    payload_sin_codigo["dteJson"]["identificacion"].pop("codigoGeneracion", None)
    venta_sin_codigo = db_conn.add_venta("2024-01-11", 30, cliente_id=cliente_emp, extra=payload_sin_codigo)
    _insert_envio(db_conn, venta_sin_codigo, codigo=None, numero="03-0004", estado="Enviado", tag="enviado", manual=0)
    venta_ids.append(venta_sin_codigo)

    venta_fuera = db_conn.add_venta(
        "2024-01-12",
        45,
        cliente_id=cliente_emp,
        extra=_dte_payload(
            tipo="03",
            fecha="2023-12-30",
            codigo="OUT-001",
            numero_control="03-0005",
            nombre="Empresa Uno",
            receptor={"nit": "06141990011019", "nrc": "1234567"},
            resumen=resumen_base,
        ),
    )
    _insert_envio(db_conn, venta_fuera, codigo="OUT-001", numero="03-0005", estado="Enviado", tag="enviado", manual=0)
    venta_ids.append(venta_fuera)

    payload_sin_fecha = _dte_payload(
        tipo="03",
        fecha="",
        codigo="SF-001",
        numero_control="03-0006",
        nombre="Empresa Uno",
        receptor={"nit": "06141990011019", "nrc": "1234567"},
        resumen=resumen_base,
    )
    payload_sin_fecha["dteJson"]["identificacion"].pop("fecEmi", None)
    venta_sin_fecha = db_conn.add_venta("2024-01-13", 35, cliente_id=cliente_emp, extra=payload_sin_fecha)
    db_conn.cursor.execute("UPDATE ventas SET fecha = '' WHERE id = ?", (venta_sin_fecha,))
    _insert_envio(db_conn, venta_sin_fecha, codigo="SF-001", numero="03-0006", estado="Enviado", tag="enviado", manual=0)
    venta_ids.append(venta_sin_fecha)

    resumen_cf = {
        "totalExenta": "0.00",
        "totalNoSuj": "0.00",
        "totalGravada": "19.00",
        "totalPagar": "20.00",
    }
    venta_cf_consumidor = db_conn.add_venta(
        "2024-01-14",
        20,
        cliente_id=cliente_nat,
        extra=_dte_payload(
            tipo="01",
            fecha="2024-01-14",
            codigo="CFD-001",
            numero_control="01-0001",
            nombre="Persona Natural",
            receptor={"dui": "01234567-8"},
            resumen=resumen_cf,
        ),
    )
    _insert_envio(db_conn, venta_cf_consumidor, codigo="CFD-001", numero="01-0001", estado="Enviado", tag="enviado", manual=0)
    venta_ids.append(venta_cf_consumidor)

    resumen_tipo02 = {
        "totalExenta": "0.00",
        "totalNoSuj": "0.00",
        "totalGravada": "8.00",
        "totalPagar": "8.00",
    }
    venta_tipo02 = db_conn.add_venta(
        "2024-01-15",
        8,
        cliente_id=cliente_nat,
        extra=_dte_payload(
            tipo="02",
            fecha="2024-01-15",
            codigo="CFD-002",
            numero_control="02-0001",
            nombre="Persona Natural",
            receptor={"dui": "01234567-8"},
            resumen=resumen_tipo02,
        ),
    )
    _insert_envio(db_conn, venta_tipo02, codigo="CFD-002", numero="02-0001", estado="Enviado", tag="enviado", manual=0)
    venta_ids.append(venta_tipo02)

    db_conn.conn.commit()

    monkeypatch.setattr(
        dte_provider,
        "_facturacion_rows",
        lambda db: _build_facturacion_rows(db_conn, venta_ids),
    )

    preview = dte_provider.get_declaracion_preview(db_conn, "202401")

    anexo_i = preview.anexo_i
    assert anexo_i.total_incluidos == 4
    assert anexo_i.candidatos == 9
    assert anexo_i.total_excluidos == 5
    assert anexo_i.conteos_por_tipo["03"]["incluidos"] == 2
    assert anexo_i.conteos_por_tipo["03"]["excluidos"] == 4
    assert anexo_i.conteos_por_tipo["05"]["incluidos"] == 1
    assert anexo_i.conteos_por_tipo["05"]["excluidos"] == 1

    override_row = next(row for row in anexo_i.incluidos if row.codigo_generacion == "OVR-001")
    assert override_row.estado_override
    assert override_row.estado_base == "pendiente"
    assert override_row.estado_manual == "enviado"

    fechas_incluidos = [row.fecha for row in anexo_i.incluidos]
    assert fechas_incluidos == sorted(fechas_incluidos)

    assert any(entry.detalle == "pendiente" for entry in anexo_i.excluidos["no_enviado"])
    assert any(entry.codigo == "ND-001" for entry in anexo_i.excluidos["duplicado"])
    assert any(entry.codigo is None for entry in anexo_i.excluidos["sin_codigo"])
    assert any(entry.detalle == "202312" for entry in anexo_i.excluidos["fuera_de_periodo"])
    assert any(entry.detalle == "sin fecha" for entry in anexo_i.excluidos["sin_fecha"])

    anexo_ii = preview.anexo_ii
    assert anexo_ii.total_incluidos == 2
    assert anexo_ii.candidatos == 2
    assert anexo_ii.conteos_por_tipo["01"]["incluidos"] == 1
    assert anexo_ii.conteos_por_tipo["02"]["incluidos"] == 1
    assert anexo_ii.conteos_por_tipo["02"]["excluidos"] == 0
    assert anexo_ii.conteos_por_tipo["10"]["incluidos"] == 0
    assert anexo_ii.conteos_por_tipo["11"]["incluidos"] == 0

    cf_preview = next(row for row in anexo_ii.incluidos if row.codigo_generacion == "CFD-001")
    assert cf_preview.totales["gravadas"] == "20.00"
    assert cf_preview.totales["total"] == "20.00"
    assert not cf_preview.identificacion


def test_collect_facturacion_dataset_includes_orphan_rows(db_conn, tmp_path):
    base_name = "20240115_0005_CreditoFiscal"
    pdf_path = tmp_path / f"{base_name}.pdf"
    json_path = tmp_path / f"{base_name}.json"

    pdf_path.write_text("pdf", encoding="utf-8")
    payload = {
        "respuesta": {
            "documento": {
                "identificacion": {
                    "numeroControl": "DTE-03-S001P001-000000000000005",
                    "codigoGeneracion": "XYZ123",
                    "tipoDte": "03",
                    "fecEmi": "2024-01-15",
                    "horEmi": "08:45:00",
                },
                "receptor": {"nombre": "Cliente Orphan"},
                "resumen": {"totalPagar": "100.50"},
            }
        }
    }
    json_path.write_text(json.dumps(payload), encoding="utf-8")

    db_conn.add_factura_pdf(None, "Crédito fiscal", str(pdf_path))

    dataset = dte_provider.collect_facturacion_dataset(db_conn, "202401")

    assert dataset.rows
    assert dataset.descartes == {}

    row = dataset.rows[0]
    assert row.get("row_type") == "orphan"
    assert row.get("codigo_generacion") == "XYZ123"
    assert row.get("cliente_nombre") == "Cliente Orphan"
    assert row.get("fecha_obj").strftime("%Y-%m-%d") == "2024-01-15"


def test_collect_dataset_includes_credito_json_from_fs(db_conn, tmp_path, monkeypatch):
    cf_dir = tmp_path / "credito_fiscal"
    archive_dir = tmp_path / "archivo_cf"
    dtes_dir = tmp_path / "dtes"
    pendientes_dir = tmp_path / "pendientes"
    for folder in (cf_dir, archive_dir, dtes_dir, pendientes_dir):
        folder.mkdir(parents=True, exist_ok=True)

    json_path = cf_dir / "20240110_credito.json"
    payload = {
        "dteJson": {
            "identificacion": {
                "tipoDte": "03",
                "fecEmi": "2024-01-10",
                "horEmi": "09:15:00",
                "numeroControl": "DTE-03-S001P001-000000000000777",
                "codigoGeneracion": "CF-ORPHAN-0001",
            },
            "receptor": {"nombre": "Cliente CF"},
            "resumen": {"totalPagar": "50.00"},
        },
        "respuesta": {"estado": "Enviado"},
    }
    json_path.write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setattr(dte_provider, "FACTURAS_CREDITO_FISCAL_DIR", str(cf_dir))
    monkeypatch.setattr(dte_provider, "FACTURAS_ARCHIVE_CREDITO_DIR", str(archive_dir))
    monkeypatch.setattr(dte_provider, "DTES_DIR", str(dtes_dir))
    monkeypatch.setattr(dte_provider, "DTES_PENDIENTES_DIR", str(pendientes_dir))

    dataset = dte_provider.collect_facturacion_dataset(db_conn, "202401")

    matching = [row for row in dataset.rows if row.get("json_path") == str(json_path)]
    assert matching, dataset.rows
    row = matching[0]
    assert row.get("row_type") == "orphan"
    assert row.get("codigo_generacion") == "CF-ORPHAN-0001"
    assert row.get("cliente_nombre") == "Cliente CF"
    assert row.get("fecha_obj").strftime("%Y-%m-%d") == "2024-01-10"


def test_estado_normalizacion_y_apto():
    assert dte_provider.normalize_estado("Procesamiento") == "recibido"
    assert dte_provider.estado_apto("Cancelada") is False
    assert dte_provider.estado_apto("rechazado", override_manual="Aceptada") is True
    assert dte_provider.estado_apto("Procesado") is True
    assert dte_provider.estado_enviado("Pendiente", override_manual="Enviado") is True
    assert dte_provider.estado_enviado("Procesado") is False
