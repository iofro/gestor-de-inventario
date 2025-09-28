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
from utils.receptor import ensure_receptor_completo
from utils.fecha import TZ_EL_SALVADOR, fecha_emision_hoy_str, normalizar_fecha_iso
from utils.monto import d2, monto_a_texto_sv, to_base_iva


logger = logging.getLogger(__name__)


Decimal_0 = Decimal("0")
Decimal_1 = Decimal("1")
Q4 = Decimal("0.0001")
IVA = Decimal("0.13")


def _pct_label(ratio: Decimal) -> str:
    """Return percentage string (e.g., ``40`` for ``0.4``)."""
    return str((ratio * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def generar_nce_desde_nota(db: DB, nota_id: int, *, ambiente: str = "00") -> dict:
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

    dte_origen = generar_dte_json(db, venta_id, tipo_dte=tipo_doc, ambiente=ambiente)
    fecha_origen = normalizar_fecha_iso(venta.get("fecha")) if venta else None
    if fecha_origen:
        identificacion = dte_origen.get("identificacion")
        if isinstance(identificacion, dict):
            identificacion["fecEmi"] = fecha_origen

    detalles = None
    if nota.get("detalles"):
        try:
            detalles = json.loads(nota["detalles"])
        except Exception:
            detalles = None

    if detalles:
        return generar_nce_desde_dte(
            db,
            dte_origen,
            None,
            detalles=detalles,
            ambiente=ambiente,
            motivo=nota.get("motivo"),
        )

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

    return generar_nce_desde_dte(
        db,
        dte_origen,
        ratio,
        ambiente=ambiente,
        motivo=nota.get("motivo"),
        monto=monto_nc,
    )


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

    tipo_doc_rel = str(origen_ident.get("tipoDte") or "").zfill(2) if origen_ident.get("tipoDte") else None
    if not tipo_doc_rel:
        tipo_doc_rel = "03" if (dte_origen.get("receptor") or {}).get("nrc") else "01"
    numero_documento = origen_ident.get("codigoGeneracion") or ""
    if isinstance(numero_documento, str):
        numero_documento = numero_documento.upper()
    doc_rel = [
        {
            "tipoDocumento": tipo_doc_rel,
            "tipoGeneracion": 2,
            "numeroDocumento": numero_documento,
            "fechaEmision": origen_ident.get("fecEmi"),
        }
    ]

    emisor = deepcopy(dte_origen.get("emisor") or {})
    receptor = ensure_receptor_completo(dte_origen.get("receptor"), ambiente)

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
    return result

