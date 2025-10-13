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
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
import copy
import json
import logging
from typing import Optional

from db import DB
from dte import (
    DTE_VERSIONES,
    generar_cabecera_dte_data,
    generar_dte_json,
    resolve_ambiente,
    sanitize_dte_payload,
    d4,
)
from utils import catalogos
from utils.catalogos import TRIBUTO_IVA, TRIBUTOS
from utils.identificacion import is_valid_nit, normalize_dui_to_nit9
from utils.env import env_flag
from utils import metrics
from utils.receptor import ensure_receptor_completo
from utils.fecha import TZ_EL_SALVADOR, fecha_ddmmaaaa, fecha_emision_hoy_str, fecha_iso
from utils.monto import d2, monto_a_texto_sv, to_base_iva
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

Decimal_0 = Decimal("0")
Decimal_1 = Decimal("1")
IVA = Decimal("0.13")


def _norm_afectacion(det: dict, original: dict | None) -> str:
    """Return normalized afectacion for ``det`` using ``original`` as fallback."""

    afectacion = str(det.get("afectacion") or "").strip().lower()
    afectacion = afectacion.replace("-", "_").replace(" ", "_")
    if afectacion:
        return afectacion
    if original:
        if Decimal(str(original.get("ventaGravada") or 0)) > Decimal_0:
            return "gravada"
        if Decimal(str(original.get("ventaExenta") or 0)) > Decimal_0:
            return "exenta"
        if Decimal(str(original.get("ventaNoSuj") or 0)) > Decimal_0:
            return "no_sujeta"
    return afectacion


def _resolver_detalle_ajuste_precio(
    det: dict,
    original: dict | None,
    monto_abs: Decimal,
) -> dict:
    """Normaliza un detalle que ajusta el precio total."""

    normalizado = dict(det)
    normalizado["_ajuste_precio"] = True

    incluye_iva = bool(
        normalizado.get("monto_incluye_iva")
        or normalizado.get("montoIncluyeIVA")
        or normalizado.get("incluyeIVA")
    )

    afectacion = _norm_afectacion(normalizado, original)

    if incluye_iva:
        base_precisa, iva_precisa = to_base_iva(monto_abs)
        base = d4(base_precisa)
        total_con_iva = monto_abs
        iva_preciso = iva_precisa
    else:
        base = normalizado.get("precio_unitario") or normalizado.get("precioUni") or monto_abs
        base = d4(base)
        total_con_iva = None
        iva_preciso = None

    grav = Decimal_0
    exenta = Decimal_0
    nosuj = Decimal_0
    if afectacion == "exenta":
        exenta = base
    elif afectacion in {"no_sujeta", "no__sujeta", "no_suj"}:
        nosuj = base
    else:
        grav = base

    normalizado["cantidad"] = d4(Decimal_1)
    normalizado["precio_unitario"] = base
    normalizado["precioUni"] = base
    normalizado["ventaGravada"] = grav
    normalizado["ventaExenta"] = exenta
    normalizado["ventaNoSuj"] = nosuj
    normalizado["ventas_gravadas"] = grav
    normalizado["ventas_exentas"] = exenta
    normalizado["ventas_no_sujetas"] = nosuj

    if "uniMedida" not in normalizado:
        if original and original.get("uniMedida") is not None:
            normalizado["uniMedida"] = original.get("uniMedida")
        else:
            normalizado["uniMedida"] = 59
    if "tipoItem" not in normalizado and original and original.get("tipoItem") is not None:
        normalizado["tipoItem"] = original.get("tipoItem")
    else:
        normalizado.setdefault("tipoItem", 1)

    desc_base = normalizado.get("descripcion") or (original.get("descripcion") if original else "")
    desc_base = str(desc_base).strip()
    if desc_base:
        normalizado["descripcion"] = f"AJUSTE PRECIO TOTAL – {desc_base}"
    else:
        normalizado["descripcion"] = "AJUSTE PRECIO TOTAL"

    codigo_base = normalizado.get("codigo") or (original.get("codigo") if original else None)
    if codigo_base:
        codigo_base = str(codigo_base)
        if not codigo_base.startswith("AJP-"):
            normalizado["codigo"] = f"AJP-{codigo_base}"
        else:
            normalizado["codigo"] = codigo_base
    else:
        normalizado["codigo"] = None

    if total_con_iva is None:
        if grav > Decimal_0:
            iva_preciso = grav * IVA
            total_con_iva = grav + iva_preciso
        else:
            total_con_iva = grav + exenta + nosuj
            iva_preciso = Decimal_0
    normalizado["_total_con_iva"] = total_con_iva
    normalizado["_iva_preciso"] = iva_preciso or Decimal_0

    return normalizado


def _resolver_detalle_ajuste_cantidad(
    det: dict, original: dict | None, *, permitir_exceder: bool = True
) -> dict:
    """Normaliza los ajustes de cantidad según el esquema ``fe-nd-v3``."""

    if not det or not det.get("ajusteCantidad"):
        return det

    normalizado = dict(det)
    cantidad_raw = normalizado.get("cantidad")
    if cantidad_raw is None:
        raise ValueError("Los ajustes por cantidad requieren el campo 'cantidad'")
    cantidad = Decimal(str(cantidad_raw))
    if cantidad <= Decimal_0:
        raise ValueError("La cantidad del ajuste debe ser mayor que cero")

    precio_raw = (
        normalizado.get("precio_unitario")
        or normalizado.get("precioUni")
        or (original.get("precioUni") if original else None)
    )
    if precio_raw is None:
        raise ValueError(
            "Los ajustes por cantidad requieren precio unitario explícito u original"
        )
    precio = Decimal(str(precio_raw))

    afectacion = str(normalizado.get("afectacion") or "").lower()
    if not afectacion and original:
        if Decimal(str(original.get("ventaGravada") or 0)) > Decimal_0:
            afectacion = "gravada"
        elif Decimal(str(original.get("ventaExenta") or 0)) > Decimal_0:
            afectacion = "exenta"
        elif Decimal(str(original.get("ventaNoSuj") or 0)) > Decimal_0:
            afectacion = "no_sujeta"

    total = d4(precio * cantidad)
    grav = normalizado.get("ventas_gravadas") or normalizado.get("ventaGravada")
    exenta = normalizado.get("ventas_exentas") or normalizado.get("ventaExenta")
    nosuj = normalizado.get("ventas_no_sujetas") or normalizado.get("ventaNoSuj")
    if grav is None and exenta is None and nosuj is None:
        if afectacion == "exenta":
            exenta = total
            grav = Decimal_0
            nosuj = Decimal_0
        elif afectacion == "no_sujeta":
            nosuj = total
            grav = Decimal_0
            exenta = Decimal_0
        else:
            grav = total
            exenta = Decimal_0
            nosuj = Decimal_0
    grav = d4(Decimal(str(grav or 0)))
    exenta = d4(Decimal(str(exenta or 0)))
    nosuj = d4(Decimal(str(nosuj or 0)))

    normalizado["cantidad"] = d4(cantidad)
    normalizado["precioUni"] = d4(precio)
    normalizado["ventaGravada"] = grav
    normalizado["ventaExenta"] = exenta
    normalizado["ventaNoSuj"] = nosuj

    if "uniMedida" not in normalizado and original and original.get("uniMedida") is not None:
        normalizado["uniMedida"] = original.get("uniMedida")
    if "tipoItem" not in normalizado and original and original.get("tipoItem") is not None:
        normalizado["tipoItem"] = original.get("tipoItem")

    return normalizado


def generar_nde_desde_nota(
    db: DB,
    nota_id: int,
    *,
    ambiente: str = "00",
    strict_snapshot: bool | None = None,
) -> dict:
    """Genera una NDE basada en la nota registrada en ``notas``."""

    ambiente = resolve_ambiente(ambiente)
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
    fecha_origen_source = None
    if snapshot and snapshot.fecha_emision:
        fecha_origen = fecha_ddmmaaaa(snapshot.fecha_emision)
        if fecha_origen:
            fecha_origen_source = "snapshot"
    if not fecha_origen and venta_id is not None:
        fecha_envio = db.get_envio_fecha_emision(venta_id)
        if fecha_envio:
            fecha_origen = fecha_envio
            fecha_origen_source = "envio"
    if not fecha_origen and venta:
        fecha_origen = fecha_ddmmaaaa(venta.get("fecha"))
        if fecha_origen:
            fecha_origen_source = "venta"
    logger.info(
        "fecha relacionada para nota %s = %s (origen: %s)",
        nota_id,
        fecha_origen,
        fecha_origen_source or "desconocido",
    )

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
        fecha_origen=fecha_origen,
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
    fecha_origen: Optional[str] = None,
) -> dict:
    """Genera la estructura JSON de una NDE."""
    ambiente = resolve_ambiente(ambiente)
    origen_ident = dte_origen.get("identificacion", {})

    cabecera = generar_cabecera_dte_data(1, 1, "06", db, ambiente=ambiente)
    now = datetime.now(TZ_EL_SALVADOR)
    fecha_emision_por_defecto = fecha_ddmmaaaa(now) or fecha_emision_hoy_str(now)
    fec_emi_hoy_iso = fecha_iso(fecha_emision_por_defecto)
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
        "fecEmi": fec_emi_hoy_iso,
        "horEmi": now.strftime("%H:%M:%S"),
        "tipoMoneda": "USD",
    }
    # NOTAS (04/05/06):
    # - identificacion.fecEmi = hoy (se reafirma en enviar_* y _enviar_documento).
    # - documentoRelacionado[].fechaEmision = fecha histórica del DTE base.
    #   Nunca copiar la histórica hacia fecEmi.

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
    numero_control = origen_ident.get("numeroControl")
    if codigo_generacion:
        numero_documento = str(codigo_generacion).upper()
        tipo_generacion = 2
    else:
        tipo_generacion = 1
        numero_documento = str(numero_control or "").strip()

    fecha_doc_rel_base = None
    if fecha_origen:
        fecha_doc_rel_base = fecha_ddmmaaaa(fecha_origen)
    if not fecha_doc_rel_base:
        fecha_doc_rel_base = fecha_ddmmaaaa(
            origen_ident.get("fechaEmision") or origen_ident.get("fecEmi")
        )
    if not fecha_doc_rel_base:
        fecha_doc_rel_base = fecha_emision_por_defecto

    doc_rel = [
        {
            "tipoDocumento": tipo_doc_rel,
            "tipoGeneracion": tipo_generacion,
            "numeroDocumento": numero_documento,
            "fechaEmision": fecha_iso(fecha_doc_rel_base),
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
        total_grav = Decimal_0
        total_exenta = Decimal_0
        total_nosuj = Decimal_0
        total_con_iva = Decimal_0
        iva_preciso_total = Decimal_0
        num = 1
        orig_items = dte_origen.get("cuerpoDocumento", [])
        for det in detalles:
            codigo = det.get("codigo")
            numitem = det.get("numItem")
            orig = None
            if codigo:
                orig = next((it for it in orig_items if it.get("codigo") == codigo), None)
            elif numitem:
                orig = next((it for it in orig_items if it.get("numItem") == numitem), None)

            ajuste_val = Decimal_0
            if det.get("ajuste") is not None:
                try:
                    ajuste_val = Decimal(str(det.get("ajuste")))
                except (InvalidOperation, ValueError) as exc:
                    raise ValueError("El ajuste monetario debe ser numérico") from exc
            ajuste_abs = ajuste_val.copy_abs()
            cantidad_informada = None
            if det.get("cantidad") is not None:
                try:
                    cantidad_informada = Decimal(str(det.get("cantidad")))
                except (InvalidOperation, ValueError) as exc:
                    raise ValueError("La cantidad debe ser numérica") from exc

            if det.get("ajusteCantidad") and ajuste_abs > Decimal_0:
                raise ValueError(
                    "Una fila no puede llevar cantidad y ajuste monetario a la vez; elige un modo"
                )
            if (
                ajuste_abs > Decimal_0
                and cantidad_informada is not None
                and cantidad_informada.copy_abs() > Decimal_0
            ):
                raise ValueError(
                    "Una fila no puede llevar cantidad y ajuste monetario a la vez; elige un modo"
                )
            if ajuste_abs > Decimal_0:
                det = _resolver_detalle_ajuste_precio(det, orig, ajuste_abs)
            else:
                det = _resolver_detalle_ajuste_cantidad(det, orig, permitir_exceder=True)

            grav = d4(det.get("ventas_gravadas") or det.get("ventaGravada") or 0)
            exenta = d4(det.get("ventas_exentas") or det.get("ventaExenta") or 0)
            nosuj = d4(det.get("ventas_no_sujetas") or det.get("ventaNoSuj") or 0)
            total_grav += grav
            total_exenta += exenta
            total_nosuj += nosuj

            precio = det.get("precio_unitario") or det.get("precioUni")
            if precio is None:
                precio = grav + exenta + nosuj
            precio = d4(precio)

            cantidad_raw = det.get("cantidad", 1)
            cantidad = d4(Decimal(str(cantidad_raw)))

            base_line = grav + exenta + nosuj
            total_line_con_iva = det.get("_total_con_iva")
            if total_line_con_iva is not None:
                total_line_con_iva = Decimal(str(total_line_con_iva))
                iva_preciso_line = total_line_con_iva - base_line
            else:
                iva_preciso_line = grav * IVA if grav > Decimal_0 else Decimal_0
                total_line_con_iva = base_line + iva_preciso_line
            total_con_iva += total_line_con_iva
            iva_preciso_total += iva_preciso_line

            codigo_det = det.get("codigo")
            if not codigo_det:
                if det.get("_ajuste_precio"):
                    codigo_det = f"AJP-{uuid_origen[:8]}-{num}"
                else:
                    codigo_det = f"ND{uuid_origen[:8]}-{num}"

            descripcion_det = det.get(
                "descripcion",
                f"Nota de débito sobre operaciones del {tipo_doc_desc} relacionado{extra_desc}",
            )

            items.append(
                {
                    "numItem": num,
                    "tipoItem": det.get("tipoItem", 1),
                    "codigo": codigo_det,
                    "descripcion": descripcion_det,
                    "cantidad": cantidad,
                    "uniMedida": det.get("uniMedida", 59),
                    "precioUni": precio,
                    "montoDescu": d4(det.get("montoDescu", 0.0)),
                    "ventaGravada": d4(grav),
                    "ventaExenta": d4(exenta),
                    "ventaNoSuj": d4(nosuj),
                    "tributos": [TRIBUTO_IVA] if grav > 0 else None,
                    "numeroDocumento": uuid_origen,
                    "codTributo": None,
                }
            )
            num += 1

        total_grav_preciso = total_grav
        total_exenta_preciso = total_exenta
        total_nosuj_preciso = total_nosuj
        total_grav = d4(total_grav)
        total_exenta = d4(total_exenta)
        total_nosuj = d4(total_nosuj)
        subtotal_preciso = total_grav_preciso + total_exenta_preciso + total_nosuj_preciso
        subtotal_ventas = d4(total_grav + total_exenta + total_nosuj)

        if total_con_iva <= Decimal_0:
            total_con_iva = subtotal_preciso

        user_total = Decimal(str(monto)) if monto is not None else None
        if user_total is not None and user_total >= subtotal_ventas:
            iva_val = d2(user_total - subtotal_ventas)
            monto_total = d2(user_total)
        else:
            iva_val = d2(iva_preciso_total)
            monto_total = d2(total_con_iva)

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
                    "tributos": None,
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
                    "tributos": None,
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
