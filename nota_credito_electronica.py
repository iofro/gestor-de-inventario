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
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
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


Decimal_0 = Decimal("0")
Decimal_1 = Decimal("1")
Q4 = Decimal("0.0001")
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
        base = base_precisa.quantize(Q4, rounding=ROUND_HALF_UP)
        total_con_iva = monto_abs
        iva_preciso = iva_precisa
    else:
        base = Decimal(str(normalizado.get("precio_unitario") or normalizado.get("precioUni") or monto_abs))
        base = base.quantize(Q4, rounding=ROUND_HALF_UP)
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

    normalizado["cantidad"] = Decimal_1.quantize(Q4)
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


def _resolver_detalle_ajuste_cantidad(
    det: dict, original: dict | None, *, permitir_exceder: bool = False
) -> dict:
    """Normaliza un detalle que ajusta cantidad a partir del documento origen.

    Cuando ``det`` indica ``ajusteCantidad`` se completan los campos
    ``cantidad``, ``precioUni`` y ``ventaGravada``/``Exenta``/``NoSuj`` en base a
    la información disponible.  Esto permite que la UI envíe únicamente la
    cantidad a acreditar y que el módulo derive los importes consistentes con el
    esquema ``fe-nc-v3``.
    """

    if not det or not det.get("ajusteCantidad"):
        return det

    normalizado = dict(det)
    cantidad_raw = normalizado.get("cantidad")
    if cantidad_raw is None:
        raise ValueError("Los ajustes por cantidad requieren el campo 'cantidad'")
    cantidad = Decimal(str(cantidad_raw))
    if cantidad <= Decimal_0:
        raise ValueError("La cantidad del ajuste debe ser mayor que cero")

    if original and not permitir_exceder:
        try:
            cantidad_origen = Decimal(str(original.get("cantidad") or 0))
        except Exception:
            cantidad_origen = Decimal_0
        if cantidad_origen > Decimal_0 and cantidad > cantidad_origen:
            raise ValueError("La cantidad del ajuste excede la línea original")

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

    total = (precio * cantidad).quantize(Q4)
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
    grav = Decimal(str(grav or 0)).quantize(Q4)
    exenta = Decimal(str(exenta or 0)).quantize(Q4)
    nosuj = Decimal(str(nosuj or 0)).quantize(Q4)

    normalizado["cantidad"] = cantidad.quantize(Q4)
    normalizado["precioUni"] = precio.quantize(Q4)
    normalizado["ventaGravada"] = grav
    normalizado["ventaExenta"] = exenta
    normalizado["ventaNoSuj"] = nosuj

    if "uniMedida" not in normalizado and original and original.get("uniMedida") is not None:
        normalizado["uniMedida"] = original.get("uniMedida")
    if "tipoItem" not in normalizado and original and original.get("tipoItem") is not None:
        normalizado["tipoItem"] = original.get("tipoItem")

    return normalizado


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

    ambiente = resolve_ambiente(ambiente)
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

    if detalles:
        resultado = generar_nce_desde_dte(
            db,
            dte_origen,
            None,
            detalles=detalles,
            ambiente=ambiente,
            motivo=nota.get("motivo"),
            fecha_origen=fecha_origen,
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
    fecha_origen: Optional[str] = None,
) -> dict:
    """Genera la estructura JSON de una NCE."""
    ambiente = resolve_ambiente(ambiente)
    if detalles is None:
        if ratio is None or ratio <= Decimal_0:
            raise ValueError("El porcentaje a acreditar debe ser mayor que cero")

    origen_ident = dte_origen.get("identificacion", {})
    cabecera = generar_cabecera_dte_data(1, 1, "05", db, ambiente=ambiente)
    now = datetime.now(TZ_EL_SALVADOR)
    fecha_emision_por_defecto = fecha_ddmmaaaa(now) or fecha_emision_hoy_str(now)
    fec_emi_hoy_iso = fecha_iso(fecha_emision_por_defecto)
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
        "fecEmi": fec_emi_hoy_iso,
        "horEmi": now.strftime("%H:%M:%S"),
        "tipoMoneda": "USD",
    }
    # NOTAS (04/05/06):
    # - identificacion.fecEmi = hoy (se reafirma en enviar_* y _enviar_documento).
    # - documentoRelacionado[].fechaEmision = fecha histórica del DTE base.
    #   Nunca copiar la histórica hacia fecEmi.

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
        total_con_iva = Decimal_0
        iva_preciso_total = Decimal_0
        num = 1
        ratio_val = ratio or Decimal_1
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
                det = _resolver_detalle_ajuste_cantidad(det, orig)

            grav = Decimal(str(det.get("ventas_gravadas") or det.get("ventaGravada") or 0)).quantize(Q4)
            exenta = Decimal(str(det.get("ventas_exentas") or det.get("ventaExenta") or 0)).quantize(Q4)
            nosuj = Decimal(str(det.get("ventas_no_sujetas") or det.get("ventaNoSuj") or 0)).quantize(Q4)
            total_grav += grav
            total_exenta += exenta
            total_nosuj += nosuj

            if orig:
                grav_orig = Decimal(str(orig.get("ventaGravada") or 0)).quantize(Q4)
                exenta_orig = Decimal(str(orig.get("ventaExenta") or 0)).quantize(Q4)
                nosuj_orig = Decimal(str(orig.get("ventaNoSuj") or 0)).quantize(Q4)
                if grav > grav_orig or exenta > exenta_orig or nosuj > nosuj_orig:
                    raise ValueError("Detalle excede montos de línea original")

            precio = det.get("precio_unitario") or det.get("precioUni")
            if precio is None:
                if orig and orig.get("precioUni") is not None:
                    precio = Decimal(str(orig.get("precioUni"))) * ratio_val
                else:
                    precio = grav + exenta + nosuj
            precio = Decimal(str(precio)).quantize(Q4)

            cantidad_raw = det.get("cantidad", 1)
            cantidad = Decimal(str(cantidad_raw)).quantize(Q4)

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
                    codigo_det = f"NC{uuid_origen[:8]}-{num}"

            descripcion_det = det.get(
                "descripcion",
                f"Nota de crédito sobre operaciones del {tipo_doc_desc} relacionado{extra_desc}",
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
                    "montoDescu": det.get("montoDescu", 0.0),
                    "ventaGravada": grav,
                    "ventaExenta": exenta,
                    "ventaNoSuj": nosuj,
                    "tributos": [TRIBUTO_IVA] if grav > 0 else None,
                    "numeroDocumento": uuid_origen,
                    "codTributo": None,
                }
            )
            num += 1

        total_grav_preciso = total_grav
        total_exenta_preciso = total_exenta
        total_nosuj_preciso = total_nosuj
        total_grav = total_grav.quantize(Q4)
        total_exenta = total_exenta.quantize(Q4)
        total_nosuj = total_nosuj.quantize(Q4)
        subtotal_preciso = total_grav_preciso + total_exenta_preciso + total_nosuj_preciso
        subtotal_ventas = (total_grav + total_exenta + total_nosuj).quantize(Q4)
        if total_con_iva <= Decimal_0:
            total_con_iva = subtotal_preciso
        iva_val = d2(iva_preciso_total)
        monto_total_operacion = d2(total_con_iva)
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
                        "codigo": f"NC{pct_text}-{uuid_origen[:8]}-N",
                        "descripcion": f"Nota de crédito {pct_text}% sobre operaciones no sujetas del {tipo_doc_desc} relacionado{extra_desc}",
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

