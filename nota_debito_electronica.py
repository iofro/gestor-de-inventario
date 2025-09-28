# coding: utf-8
"""Generación de Nota de Débito Electrónica (NDE).

Este módulo construye la estructura JSON requerida por el Ministerio de
Hacienda de El Salvador para una Nota de Débito Electrónica (tipoDte ``06``).
Se genera a partir de un DTE de origen y permite acreditar montos o
proporciones del documento original.
"""
from __future__ import annotations

import time
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
import copy
import json
import logging
from typing import Optional

from db import DB
from dte import (
    DTE_VERSIONES,
    generar_cabecera_dte_data,
    generar_dte_json,
    sanitize_dte_payload,
    d4,
)
from utils import catalogos
from utils.catalogos import TRIBUTO_IVA, TRIBUTOS
from utils.identificacion import is_valid_nit, normalize_dui_to_nit9
from utils.env import env_flag
from utils import metrics
from utils.receptor import ensure_receptor_completo
from utils.fecha import TZ_EL_SALVADOR, fecha_emision_hoy_str, normalizar_fecha_iso
from utils.monto import d2, monto_a_texto_sv
from utils.sanitize import solo_digitos
from utils.snapshot import SnapshotNotFoundError, normalize_snapshot


logger = logging.getLogger(__name__)


def _normalize_dui(value: str | None) -> str | None:
    """Return a 9-digit representation of ``value`` if possible."""

    if value is None:
        return None
    try:
        return normalize_dui_to_nit9(value)
    except ValueError:
        digits = solo_digitos(value)
        if len(digits) == 9:
            return digits
    return None


def _search_dui(data: object) -> str | None:
    """Search ``data`` recursively for a DUI (``tipoDocumento`` ``13``)."""

    if isinstance(data, dict):
        tipo_doc = data.get("tipoDocumento")
        if tipo_doc is not None:
            tipo_doc = str(tipo_doc).zfill(2)
            if tipo_doc == "13":
                for key in ("numDocumento", "numDoc", "numeroDocumento"):
                    dui = _normalize_dui(data.get(key))
                    if dui:
                        return dui
        for value in data.values():
            dui = _search_dui(value)
            if dui:
                return dui
    elif isinstance(data, (list, tuple)):
        for item in data:
            dui = _search_dui(item)
            if dui:
                return dui
    return None


STRICT_SNAPSHOT_DEFAULT = env_flag("STRICT_SNAPSHOT", default=True)


def generar_nde_desde_nota(
    db: DB,
    nota_id: int,
    *,
    ambiente: str = "00",
    strict_snapshot: bool | None = None,
) -> dict:
    """Genera una NDE basada en la nota registrada en ``notas``."""

    strict = STRICT_SNAPSHOT_DEFAULT if strict_snapshot is None else bool(strict_snapshot)
    start = time.perf_counter()
    row = db.cursor.execute("SELECT * FROM notas WHERE id=?", (nota_id,)).fetchone()
    if not row:
        raise ValueError("Nota no encontrada")
    nota = dict(row)
    if nota.get("tipo") != "debito":
        raise ValueError("La nota indicada no es de débito")

    venta_id = nota.get("venta_id")
    venta = db.get_venta_by_id(venta_id) if venta_id is not None else None
    credito_fiscal = (
        db.get_venta_credito_fiscal(venta_id) if venta_id is not None else None
    )
    tipo_doc = "03" if credito_fiscal else "01"

    snapshot = db.get_snapshot_by_venta(venta_id) if venta_id is not None else None
    source_used = "db"
    if snapshot:
        dte_origen = normalize_snapshot(snapshot.payload)
        source_used = "snapshot"
        uuid_origen = snapshot.uuid.upper() if snapshot.uuid else None
    else:
        if strict and venta_id is not None:
            raise SnapshotNotFoundError(venta_id, nota_id)
        dte_origen = generar_dte_json(
            db,
            venta_id,
            tipo_dte=tipo_doc,
            ambiente=ambiente,
            _allow_missing_venta=True,
        )
        origen_ident_tmp = dte_origen.get("identificacion") or {}
        codigo_tmp = origen_ident_tmp.get("codigoGeneracion")
        uuid_origen = str(codigo_tmp).upper() if codigo_tmp else None

    fecha_origen = None
    if snapshot and snapshot.fecha_emision:
        fecha_origen = normalizar_fecha_iso(snapshot.fecha_emision)
    elif venta:
        fecha_origen = normalizar_fecha_iso(venta.get("fecha"))
    if fecha_origen:
        identificacion = dte_origen.get("identificacion")
        if isinstance(identificacion, dict) and not identificacion.get("fecEmi"):
            identificacion["fecEmi"] = fecha_origen

    detalles = None
    if nota.get("detalles"):
        try:
            detalles = json.loads(nota["detalles"])
        except Exception:
            detalles = None

    resultado = generar_nde_desde_dte(
        db,
        dte_origen,
        detalles,
        nota.get("monto"),
        nota.get("motivo"),
        ambiente=ambiente,
    )

    doc_rel = resultado.get("documentoRelacionado") or []
    rel = doc_rel[0] if doc_rel else {}
    duration_ms = (time.perf_counter() - start) * 1000
    metrics.inc(f"notes_source_used.{source_used}")
    logger.info(
        "NDE relaciona tipo=%s uuid=%s num=%s fec=%s fuente=%s nota_id=%s venta_id=%s dur_ms=%.3f",
        rel.get("tipoDocumento"),
        uuid_origen,
        rel.get("numeroDocumento"),
        rel.get("fechaEmision"),
        source_used,
        nota_id,
        venta_id,
        duration_ms,
    )
    return resultado


def generar_nde_desde_dte(
    db: DB,
    dte_origen: dict,
    detalles: list | None,
    monto: float | None,
    motivo: str | None = None,
    *,
    ambiente: str = "00",
) -> dict:
    """Genera la estructura JSON de una NDE."""
    origen_ident = dte_origen.get("identificacion", {})

    cabecera = generar_cabecera_dte_data(1, 1, "06", db, ambiente=ambiente)
    now = datetime.now(TZ_EL_SALVADOR)
    identificacion = {
        "version": DTE_VERSIONES["06"],
        "ambiente": ambiente,
        "tipoDte": "06",
        "numeroControl": cabecera["numero_control"],
        "codigoGeneracion": cabecera["codigo_generacion"].upper(),
        "tipoModelo": cabecera["tipo_modelo"],
        "tipoOperacion": cabecera["tipo_operacion"],
        "tipoContingencia": cabecera["tipo_contingencia"],
        "motivoContin": cabecera["motivo_contin"],
        "fecEmi": fecha_emision_hoy_str(now),
        "horEmi": now.strftime("%H:%M:%S"),
        "tipoMoneda": "USD",
    }

    tipo_raw = origen_ident.get("tipoDte")
    if isinstance(tipo_raw, int):
        tipo_doc_rel = f"{tipo_raw:02d}"
    elif isinstance(tipo_raw, str):
        tipo_str = tipo_raw.strip()
        if tipo_str.isdigit() and len(tipo_str) <= 2:
            tipo_doc_rel = f"{int(tipo_str):02d}"
        else:
            tipo_doc_rel = tipo_str or None
    else:
        tipo_doc_rel = None
    if not tipo_doc_rel:
        tipo_doc_rel = "03" if (dte_origen.get("receptor") or {}).get("nrc") else "01"

    codigo_generacion = origen_ident.get("codigoGeneracion")
    if codigo_generacion:
        numero_documento = str(codigo_generacion).upper()
        tipo_generacion = 2
    else:
        tipo_generacion = 1
        numero_documento = (
            origen_ident.get("numeroDocumento")
            or origen_ident.get("numeroControl")
            or ""
        )
        numero_documento = str(numero_documento).strip()

    fecha_doc_rel = normalizar_fecha_iso(
        origen_ident.get("fecEmi") or origen_ident.get("fechaEmision")
    )
    doc_rel = [
        {
            "tipoDocumento": tipo_doc_rel,
            "tipoGeneracion": tipo_generacion,
            "numeroDocumento": numero_documento,
            "fechaEmision": fecha_doc_rel,
        }
    ]

    emisor = copy.deepcopy(dte_origen.get("emisor", {}))
    receptor_origen = dte_origen.get("receptor") or {}
    receptor_base = copy.deepcopy(receptor_origen)
    nit_digits = solo_digitos(receptor_base.get("nit"))
    if nit_digits and is_valid_nit(nit_digits):
        receptor_base["nit"] = nit_digits
    else:
        receptor_base.pop("nit", None)
    if not (nit_digits and is_valid_nit(nit_digits)):
        dui = (
            _search_dui(receptor_origen)
            or _search_dui(dte_origen.get("extension"))
            or _search_dui(dte_origen.get("otrosDocumentos"))
        )
        if dui:
            receptor_base["nit"] = dui
    receptor = ensure_receptor_completo(receptor_base, ambiente)
    final_nit = solo_digitos(receptor.get("nit"))
    if final_nit and is_valid_nit(final_nit):
        receptor["nit"] = final_nit

    nrc_original = receptor_origen.get("nrc")
    preserve_nrc_null = False
    if (
        tipo_doc_rel == "01"
        or not nrc_original
        or str(nrc_original).strip() in {"", "0"}
    ):
        receptor["nrc"] = None
        preserve_nrc_null = True

    orig_resumen = dte_origen.get("resumen", {})
    items: list[dict] = []
    uuid_origen = numero_documento if tipo_generacion == 2 else ""
    tipo_doc_desc = catalogos.DTE_TIPOS.get(origen_ident.get("tipoDte", ""), "documento")
    extra_desc = f": {motivo}" if motivo else ""

    if detalles:
        total_grav = Decimal("0")
        total_exenta = Decimal("0")
        total_nosuj = Decimal("0")
        num = 1
        for det in detalles:
            grav = Decimal(str(det.get("ventas_gravadas") or det.get("ventaGravada") or 0))
            exenta = Decimal(str(det.get("ventas_exentas") or det.get("ventaExenta") or 0))
            nosuj = Decimal(str(det.get("ventas_no_sujetas") or det.get("ventaNoSuj") or 0))
            total_grav += grav
            total_exenta += exenta
            total_nosuj += nosuj
            precio = det.get("precio_unitario") or det.get("precioUni")
            if precio is None:
                precio = grav + exenta + nosuj
            precio = d4(precio)
            cantidad = det.get("cantidad", 1)
            items.append(
                {
                    "numItem": num,
                    "tipoItem": det.get("tipoItem", 1),
                    "codigo": det.get("codigo", f"ND{uuid_origen[:8]}-{num}"),
                    "descripcion": det.get(
                        "descripcion",
                        f"Nota de débito sobre operaciones del {tipo_doc_desc} relacionado{extra_desc}",
                    ),
                    "cantidad": cantidad,
                    "uniMedida": det.get("uniMedida", 59),
                    "precioUni": precio,
                    "montoDescu": d4(det.get("montoDescu", 0.0)),
                    "ventaGravada": d4(grav),
                    "ventaExenta": d4(exenta),
                    "ventaNoSuj": d4(nosuj),
                    "tributos": [TRIBUTO_IVA] if grav > 0 else [],
                    "numeroDocumento": uuid_origen,
                    "codTributo": None,
                }
            )
            num += 1

        total_grav = d4(total_grav)
        total_exenta = d4(total_exenta)
        total_nosuj = d4(total_nosuj)
        subtotal_ventas = total_grav + total_exenta + total_nosuj

        user_total = Decimal(str(monto)) if monto is not None else None
        if user_total is not None and user_total >= subtotal_ventas:
            iva_val = d2(user_total - subtotal_ventas)
            monto_total = d2(user_total)
        else:
            iva_val = d2(total_grav * Decimal("0.13"))
            monto_total = d2(subtotal_ventas + iva_val)

        total_grav = d2(total_grav)
        total_exenta = d2(total_exenta)
        total_nosuj = d2(total_nosuj)
        subtotal_ventas = d2(subtotal_ventas)
    else:
        if monto is None:
            raise ValueError("Se requiere monto para nota de débito")
        total_origen = Decimal(
            str(
                orig_resumen.get("montoTotalOperacion")
                or orig_resumen.get("totalPagar")
                or 0
            )
        )
        if total_origen <= 0:
            raise ValueError("El documento de origen no tiene total válido")
        ratio = Decimal(str(monto)) / total_origen
        pct_text = str((ratio * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        total_grav = d2(Decimal(str(orig_resumen.get("totalGravada", 0))) * ratio)
        total_exenta = d2(Decimal(str(orig_resumen.get("totalExenta", 0))) * ratio)
        total_nosuj = d2(Decimal(str(orig_resumen.get("totalNoSuj", 0))) * ratio)
        num = 1
        if total_grav > 0:
            items.append(
                {
                    "numItem": num,
                    "tipoItem": 1,
                    "codigo": f"ND{pct_text}-{uuid_origen[:8]}-G",
                    "descripcion": f"Nota de débito {pct_text}% sobre operaciones gravadas del {tipo_doc_desc} relacionado{extra_desc}",
                    "cantidad": 1,
                    "uniMedida": 59,
                    "precioUni": total_grav,
                    "montoDescu": 0.0,
                    "ventaGravada": total_grav,
                    "ventaExenta": 0.0,
                    "ventaNoSuj": 0.0,
                    "tributos": [TRIBUTO_IVA],
                    "numeroDocumento": uuid_origen,
                    "codTributo": None,
                }
            )
            num += 1
        if total_exenta > 0:
            items.append(
                {
                    "numItem": num,
                    "tipoItem": 1,
                    "codigo": f"ND{pct_text}-{uuid_origen[:8]}-E",
                    "descripcion": f"Nota de débito {pct_text}% sobre operaciones exentas del {tipo_doc_desc} relacionado{extra_desc}",
                    "cantidad": 1,
                    "uniMedida": 59,
                    "precioUni": total_exenta,
                    "montoDescu": 0.0,
                    "ventaGravada": 0.0,
                    "ventaExenta": total_exenta,
                    "ventaNoSuj": 0.0,
                    "tributos": [],
                    "numeroDocumento": uuid_origen,
                    "codTributo": None,
                }
            )
            num += 1
        if total_nosuj > 0:
            items.append(
                {
                    "numItem": num,
                    "tipoItem": 1,
                    "codigo": f"ND{pct_text}-{uuid_origen[:8]}-N",
                    "descripcion": f"Nota de débito {pct_text}% sobre operaciones no sujetas del {tipo_doc_desc} relacionado{extra_desc}",
                    "cantidad": 1,
                    "uniMedida": 59,
                    "precioUni": total_nosuj,
                    "montoDescu": 0.0,
                    "ventaGravada": 0.0,
                    "ventaExenta": 0.0,
                    "ventaNoSuj": total_nosuj,
                    "tributos": [],
                    "numeroDocumento": uuid_origen,
                    "codTributo": None,
                }
            )

        subtotal_ventas = total_grav + total_exenta + total_nosuj
        orig_total = Decimal(str(orig_resumen.get("montoTotalOperacion", 0))) * (
            ratio if "ratio" in locals() else Decimal("1")
        )
        iva_val = d2(orig_total - subtotal_ventas)
        monto_total = d2(orig_total)

    tributos_resumen: list[dict] = []
    if iva_val > 0:
        tributos_resumen.append(
            {
                "codigo": TRIBUTO_IVA,
                "descripcion": TRIBUTOS.get(TRIBUTO_IVA, ""),
                "valor": iva_val,
            }
        )
    resumen = {
        "totalNoSuj": total_nosuj,
        "totalExenta": total_exenta,
        "totalGravada": total_grav,
        "subTotal": subtotal_ventas,
        "subTotalVentas": subtotal_ventas,
        "descuNoSuj": 0.0,
        "descuExenta": 0.0,
        "descuGravada": 0.0,
        "totalDescu": 0.0,
        "ivaPerci1": 0.0,
        "ivaRete1": 0.0,
        "reteRenta": 0.0,
        "condicionOperacion": dte_origen.get("resumen", {}).get("condicionOperacion", 1),
        "numPagoElectronico": dte_origen.get("resumen", {}).get("numPagoElectronico"),
        "tributos": tributos_resumen,
        "montoTotalOperacion": monto_total,
        "totalLetras": monto_a_texto_sv(monto_total),
    }

    data = {
        "identificacion": identificacion,
        "documentoRelacionado": doc_rel,
        "emisor": emisor,
        "receptor": receptor,
        "cuerpoDocumento": items,
        "resumen": resumen,
        "ventaTercero": None,
        "extension": None,
        "apendice": None,
    }

    logger.info(
        "NDE relaciona tipo=%s gen=%s num=%s fec=%s sello=%s",
        doc_rel[0].get("tipoDocumento"),
        origen_ident.get("codigoGeneracion"),
        origen_ident.get("numeroControl"),
        origen_ident.get("fecEmi"),
        dte_origen.get("selloRecibido"),
    )
    schema = catalogos.get_dte_schema("06")
    result = sanitize_dte_payload(data, schema)
    if preserve_nrc_null:
        result.setdefault("receptor", {})["nrc"] = None
    return result


__all__ = ["generar_nde_desde_dte", "generar_nde_desde_nota"]
