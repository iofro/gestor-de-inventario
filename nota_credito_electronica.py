# coding: utf-8
"""Generación de Nota de Crédito Electrónica (NCE).

Este módulo construye la estructura JSON requerida por el Ministerio de
Hacienda de El Salvador para una Nota de Crédito Electrónica (tipoDte ``05``).
Se crea a partir de un DTE de origen (típicamente un Comprobante de Crédito
Fiscal) y permite prorratear un monto o porcentaje del documento original.

La implementación se basa en los catálogos y utilidades existentes en el
proyecto ``gestor-de-inventario``.
"""
from __future__ import annotations

import time
from copy import deepcopy
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
import json
import logging
from typing import Optional

from db import DB
from dte import (
    DTE_VERSIONES,
    generar_cabecera_dte_data,
    generar_dte_json,
    sanitize_dte_payload,
)
from utils import catalogos
from utils.catalogos import TRIBUTO_IVA, TRIBUTOS
from utils.identificacion import is_valid_nit, normalize_dui_to_nit9
from utils.env import env_flag
from utils import metrics
from utils.receptor import ensure_receptor_completo
from utils.fecha import TZ_EL_SALVADOR, fecha_emision_hoy_str, normalizar_fecha_iso
from utils.monto import d2, monto_a_texto_sv, to_base_iva
from utils.sanitize import solo_digitos
from utils.snapshot import SnapshotNotFoundError, normalize_snapshot


logger = logging.getLogger(__name__)


Decimal_0 = Decimal("0")
Decimal_1 = Decimal("1")
Q4 = Decimal("0.0001")
IVA = Decimal("0.13")

STRICT_SNAPSHOT_DEFAULT = env_flag("STRICT_SNAPSHOT", default=True)


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


def _pct_label(ratio: Decimal) -> str:
    """Return percentage string (e.g., ``40`` for ``0.4``)."""
    return str((ratio * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def generar_nce_desde_nota(
    db: DB,
    nota_id: int,
    *,
    ambiente: str = "00",
    strict_snapshot: bool | None = None,
) -> dict:
    """Genera una NCE basada en la nota registrada en ``notas``.

    Parameters
    ----------
    db:
        Conexión a la base de datos.
    nota_id:
        Identificador de la nota en la tabla ``notas``.
    ambiente:
        Código de ambiente (``00`` pruebas, ``01`` producción).
    """

    strict = STRICT_SNAPSHOT_DEFAULT if strict_snapshot is None else bool(strict_snapshot)
    start = time.perf_counter()
    row = db.cursor.execute("SELECT * FROM notas WHERE id=?", (nota_id,)).fetchone()
    if not row:
        raise ValueError("Nota no encontrada")
    nota = dict(row)
    if nota.get("tipo") != "credito":
        raise ValueError("La nota indicada no es de crédito")

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

    if detalles:
        resultado = generar_nce_desde_dte(
            db,
            dte_origen,
            None,
            detalles=detalles,
            ambiente=ambiente,
            motivo=nota.get("motivo"),
        )
    else:
        resumen_origen = dte_origen.get("resumen", {})
        total_origen = Decimal(
            str(
                resumen_origen.get("montoTotalOperacion")
                or resumen_origen.get("totalPagar")
                or 0
            )
        )
        monto_nc = Decimal(str(nota.get("monto", 0)))
        if total_origen <= Decimal_0:
            raise ValueError("El documento de origen no tiene total válido")
        if monto_nc > total_origen:
            raise ValueError("Monto excede total del documento de origen")
        ratio = (monto_nc / total_origen).quantize(Decimal("0.0001"))
        resultado = generar_nce_desde_dte(
            db,
            dte_origen,
            ratio,
            ambiente=ambiente,
            motivo=nota.get("motivo"),
            monto=monto_nc,
        )

    doc_rel = resultado.get("documentoRelacionado") or []
    rel = doc_rel[0] if doc_rel else {}
    duration_ms = (time.perf_counter() - start) * 1000
    metrics.inc(f"notes_source_used.{source_used}")
    if (
        fecha_origen
        and rel.get("fechaEmision")
        and rel.get("fechaEmision") != fecha_origen
    ):
        logger.warning(
            "documentoRelacionado.fechaEmision: valor no verificable localmente nota_id=%s venta_id=%s uuid=%s",
            nota_id,
            venta_id,
            uuid_origen,
        )
    logger.info(
        "NCE relaciona tipo=%s uuid=%s num=%s fec=%s fuente=%s nota_id=%s venta_id=%s dur_ms=%.3f",
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


def generar_nce_desde_dte(
    db: DB,
    dte_origen: dict,
    ratio: Decimal | None,
    *,
    detalles: Optional[list] = None,
    ambiente: str = "00",
    motivo: Optional[str] = None,
    monto: Decimal | None = None,
) -> dict:
    """Genera la estructura JSON de una NCE."""
    if detalles is None:
        if ratio is None or ratio <= Decimal_0:
            raise ValueError("El porcentaje a acreditar debe ser mayor que cero")

    origen_ident = dte_origen.get("identificacion", {})
    cabecera = generar_cabecera_dte_data(1, 1, "05", db, ambiente=ambiente)
    now = datetime.now(TZ_EL_SALVADOR)
    identificacion = {
        "version": DTE_VERSIONES["05"],
        "ambiente": ambiente,
        "tipoDte": "05",
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

    receptor_origen = dte_origen.get("receptor") or {}
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
        tipo_doc_rel = "03" if receptor_origen.get("nrc") else "01"

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

    emisor = deepcopy(dte_origen.get("emisor") or {})
    receptor_base = deepcopy(receptor_origen)
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
    uuid_origen = origen_ident.get("codigoGeneracion", "")
    tipo_doc_desc = catalogos.DTE_TIPOS.get(origen_ident.get("tipoDte", ""), "documento")
    extra_desc = f": {motivo}" if motivo else ""

    if detalles:
        total_grav = Decimal_0
        total_exenta = Decimal_0
        total_nosuj = Decimal_0
        num = 1
        ratio_val = ratio or Decimal_1
        orig_items = dte_origen.get("cuerpoDocumento", [])
        for det in detalles:
            grav = Decimal(str(det.get("ventas_gravadas") or det.get("ventaGravada") or 0)).quantize(Q4)
            exenta = Decimal(str(det.get("ventas_exentas") or det.get("ventaExenta") or 0)).quantize(Q4)
            nosuj = Decimal(str(det.get("ventas_no_sujetas") or det.get("ventaNoSuj") or 0)).quantize(Q4)
            total_grav += grav
            total_exenta += exenta
            total_nosuj += nosuj
            precio = det.get("precio_unitario") or det.get("precioUni")
            codigo = det.get("codigo")
            numitem = det.get("numItem")
            orig = None
            if codigo:
                orig = next((it for it in orig_items if it.get("codigo") == codigo), None)
            elif numitem:
                orig = next((it for it in orig_items if it.get("numItem") == numitem), None)
            if orig:
                grav_orig = Decimal(str(orig.get("ventaGravada") or 0)).quantize(Q4)
                exenta_orig = Decimal(str(orig.get("ventaExenta") or 0)).quantize(Q4)
                nosuj_orig = Decimal(str(orig.get("ventaNoSuj") or 0)).quantize(Q4)
                if grav > grav_orig or exenta > exenta_orig or nosuj > nosuj_orig:
                    raise ValueError("Detalle excede montos de línea original")
            if precio is None:
                if orig and orig.get("precioUni") is not None:
                    precio = Decimal(str(orig.get("precioUni"))) * ratio_val
                else:
                    precio = grav + exenta + nosuj
            precio = Decimal(str(precio)).quantize(Q4)
            cantidad = det.get("cantidad", 1)
            items.append(
                {
                    "numItem": num,
                    "tipoItem": det.get("tipoItem", 1),
                    "codigo": det.get("codigo", f"NC{uuid_origen[:8]}-{num}"),
                    "descripcion": det.get(
                        "descripcion",
                        f"Nota de crédito sobre operaciones del {tipo_doc_desc} relacionado{extra_desc}",
                    ),
                    "cantidad": cantidad,
                    "uniMedida": det.get("uniMedida", 59),
                    "precioUni": precio,
                    "montoDescu": det.get("montoDescu", 0.0),
                    "ventaGravada": grav,
                    "ventaExenta": exenta,
                    "ventaNoSuj": nosuj,
                    "tributos": [TRIBUTO_IVA] if grav > 0 else [],
                    "numeroDocumento": uuid_origen,
                    "codTributo": None,
                }
            )
            num += 1
        total_grav = total_grav.quantize(Q4)
        total_exenta = total_exenta.quantize(Q4)
        total_nosuj = total_nosuj.quantize(Q4)
        subtotal_ventas = (total_grav + total_exenta + total_nosuj).quantize(Q4)
        # Cuando los montos se calculan a partir de ``detalles`` evitamos
        # recurrir al total original del documento de origen. El IVA se obtiene
        # directamente de las ventas gravadas parciales y el total de la
        # operación se compone sumando dicho IVA al subtotal calculado.
        iva_val = d2(total_grav * IVA)
        monto_total_operacion = d2(subtotal_ventas + iva_val)
    else:
        if monto is not None:
            monto_abs = Decimal(str(monto)).copy_abs()
            monto_total_operacion = d2(monto_abs)
            base_precisa, _ = to_base_iva(monto_abs)
            # El monto de la nota ya incluye IVA, por lo que se separa la
            # porción gravada manteniendo mayor precisión (8 decimales) y
            # posteriormente se redondea a 2 decimales para las secciones que
            # lo requieren.  El IVA se obtiene como la diferencia entre el
            # total ingresado por el usuario y la base gravada redondeada,
            # asegurando que ambos componentes sumen el total original.
            base_redondeada = d2(base_precisa)
            total_grav = base_redondeada.quantize(Q4)
            total_exenta = Decimal_0
            total_nosuj = Decimal_0
            subtotal_ventas = total_grav
            iva_val = d2(monto_total_operacion - base_redondeada)
            num = 1
            pct_text = _pct_label(ratio) if ratio is not None else "100"
            if total_grav > 0:
                items.append(
                    {
                        "numItem": num,
                        "tipoItem": 1,
                        "codigo": f"NC{pct_text}-{uuid_origen[:8]}-G",
                        "descripcion": (
                            f"Nota de crédito {pct_text}% sobre operaciones gravadas del {tipo_doc_desc} relacionado{extra_desc}"
                            if ratio is not None
                            else f"Nota de crédito sobre operaciones gravadas del {tipo_doc_desc} relacionado{extra_desc}"
                        ),
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
        else:
            ratio_val = ratio or Decimal_1
            total_grav = (Decimal(str(orig_resumen.get("totalGravada", 0))) * ratio_val).quantize(Q4)
            total_exenta = (Decimal(str(orig_resumen.get("totalExenta", 0))) * ratio_val).quantize(Q4)
            total_nosuj = (Decimal(str(orig_resumen.get("totalNoSuj", 0))) * ratio_val).quantize(Q4)

            num = 1
            pct_text = _pct_label(ratio)
            if total_grav > 0:
                items.append(
                    {
                        "numItem": num,
                        "tipoItem": 1,
                        "codigo": f"NC{pct_text}-{uuid_origen[:8]}-G",
                        "descripcion": f"Nota de crédito {pct_text}% sobre operaciones gravadas del {tipo_doc_desc} relacionado{extra_desc}",
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
                        "codigo": f"NC{pct_text}-{uuid_origen[:8]}-E",
                        "descripcion": f"Nota de crédito {pct_text}% sobre operaciones exentas del {tipo_doc_desc} relacionado{extra_desc}",
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
                        "codigo": f"NC{pct_text}-{uuid_origen[:8]}-N",
                        "descripcion": f"Nota de crédito {pct_text}% sobre operaciones no sujetas del {tipo_doc_desc} relacionado{extra_desc}",
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
            subtotal_ventas = (total_grav + total_exenta + total_nosuj).quantize(Q4)
            orig_total_base = (
                orig_resumen.get("montoTotalOperacion")
                or orig_resumen.get("totalPagar")
                or 0
            )
            orig_total = Decimal(str(orig_total_base)) * ratio_val
            iva_val = d2(orig_total - subtotal_ventas)
            monto_total_operacion = d2(orig_total)

    tributos_resumen = []
    if iva_val > 0:
        tributos_resumen.append(
            {
                "codigo": TRIBUTO_IVA,
                "descripcion": TRIBUTOS.get(TRIBUTO_IVA, ""),
                "valor": iva_val,
            }
        )
    resumen = {
        "totalNoSuj": d2(total_nosuj),
        "totalExenta": d2(total_exenta),
        "totalGravada": d2(total_grav),
        "subTotal": d2(subtotal_ventas),
        "subTotalVentas": d2(subtotal_ventas),
        "descuNoSuj": 0.0,
        "descuExenta": 0.0,
        "descuGravada": 0.0,
        "totalDescu": 0.0,
        "ivaPerci1": 0.0,
        "ivaRete1": 0.0,
        "reteRenta": 0.0,
        "condicionOperacion": orig_resumen.get("condicionOperacion", 1),
        "tributos": tributos_resumen,
        "montoTotalOperacion": monto_total_operacion,
        "totalLetras": monto_a_texto_sv(monto_total_operacion),
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
        "NCE relaciona tipo=%s gen=%s num=%s fec=%s sello=%s",
        doc_rel[0].get("tipoDocumento"),
        origen_ident.get("codigoGeneracion"),
        origen_ident.get("numeroControl"),
        origen_ident.get("fecEmi"),
        dte_origen.get("selloRecibido"),
    )
    schema = catalogos.get_dte_schema("05")
    result = sanitize_dte_payload(data, schema)
    if preserve_nrc_null:
        result.setdefault("receptor", {})["nrc"] = None
    return result

