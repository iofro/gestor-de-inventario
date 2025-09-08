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

from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
import json
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
from utils.fecha import TZ_EL_SALVADOR, fecha_emision_hoy_str
from utils.monto import d2, monto_a_texto_sv
from utils.sanitize import limpiar_documentos


Decimal_0 = Decimal("0")
Decimal_1 = Decimal("1")
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
    if venta_id is None:
        raise ValueError("La nota no está asociada a una venta")

    venta_row = db.cursor.execute(
        "SELECT cliente_id, total FROM ventas WHERE id=?", (venta_id,)
    ).fetchone()
    if not venta_row:
        raise ValueError("Venta no encontrada")
    venta = dict(venta_row)
    tipo_doc = "01"
    if not db.get_venta_credito_fiscal(venta_id) and not venta.get("cliente_id"):
        # Se asume comprobante de crédito fiscal cuando no hay cliente asociado
        tipo_doc = "03"

    dte_origen = generar_dte_json(db, venta_id, tipo_dte=tipo_doc, ambiente=ambiente)

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

    total_origen = Decimal(str(dte_origen.get("resumen", {}).get("montoTotalOperacion", 0)))
    monto_nc = Decimal(str(nota.get("monto", 0)))
    if total_origen <= Decimal_0:
        raise ValueError("El documento de origen no tiene total válido")
    ratio = (monto_nc / total_origen).quantize(Decimal("0.0001"))

    return generar_nce_desde_dte(
        db,
        dte_origen,
        ratio,
        ambiente=ambiente,
        motivo=nota.get("motivo"),
    )


def generar_nce_desde_dte(
    db: DB,
    dte_origen: dict,
    ratio: Decimal | None,
    *,
    detalles: Optional[list] = None,
    ambiente: str = "00",
    motivo: Optional[str] = None,
) -> dict:
    """Genera la estructura JSON de una NCE."""
    if detalles is None:
        if ratio is None or ratio <= Decimal_0:
            raise ValueError("El porcentaje a acreditar debe ser mayor que cero")

    cabecera = generar_cabecera_dte_data(1, 1, "05", db, ambiente=ambiente)
    now = datetime.now(TZ_EL_SALVADOR)
    identificacion = {
        "version": DTE_VERSIONES["05"],
        "ambiente": ambiente,
        "tipoDte": "05",
        "numeroControl": cabecera["numero_control"],
        "codigoGeneracion": cabecera["codigo_generacion"],
        "tipoModelo": cabecera["tipo_modelo"],
        "tipoOperacion": cabecera["tipo_operacion"],
        "tipoContingencia": cabecera["tipo_contingencia"],
        "motivoContin": cabecera["motivo_contin"],
        "fecEmi": fecha_emision_hoy_str(now),
        "horEmi": now.strftime("%H:%M:%S"),
        "tipoMoneda": "USD",
    }

    origen_ident = dte_origen.get("identificacion", {})
    doc_rel = [
        {
            "tipoDocumento": origen_ident.get("tipoDte"),
            "tipoGeneracion": 2,
            "numeroDocumento": origen_ident.get("codigoGeneracion"),
            "fechaEmision": origen_ident.get("fecEmi"),
        }
    ]

    emisor = dte_origen.get("emisor")
    receptor = dte_origen.get("receptor")
    limpiar_documentos(emisor)
    limpiar_documentos(receptor)

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
        for det in detalles:
            grav = Decimal(str(det.get("ventas_gravadas") or det.get("ventaGravada") or 0))
            exenta = Decimal(str(det.get("ventas_exentas") or det.get("ventaExenta") or 0))
            nosuj = Decimal(str(det.get("ventas_no_sujetas") or det.get("ventaNoSuj") or 0))
            total_grav += grav
            total_exenta += exenta
            total_nosuj += nosuj
            precio = det.get("precio_unitario") or det.get("precioUni")
            if precio is None:
                # Use Decimal for internal calculations; presentation can cast to float
                precio = grav + exenta + nosuj
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
                    "ventaGravada": d2(grav),
                    "ventaExenta": d2(exenta),
                    "ventaNoSuj": d2(nosuj),
                    "tributos": [TRIBUTO_IVA] if grav > 0 else [],
                    "numeroDocumento": uuid_origen,
                    "codTributo": None,
                }
            )
            num += 1
        total_grav = d2(total_grav)
        total_exenta = d2(total_exenta)
        total_nosuj = d2(total_nosuj)
    else:
        total_grav = Decimal(str(orig_resumen.get("totalGravada", 0))) * ratio
        total_exenta = Decimal(str(orig_resumen.get("totalExenta", 0))) * ratio
        total_nosuj = Decimal(str(orig_resumen.get("totalNoSuj", 0))) * ratio

        total_grav = d2(total_grav)
        total_exenta = d2(total_exenta)
        total_nosuj = d2(total_nosuj)

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

    subtotal_ventas = total_grav + total_exenta + total_nosuj
    iva_val = d2(Decimal(str(total_grav)) * IVA)
    tributos_resumen = []
    if iva_val > 0:
        tributos_resumen.append(
            {
                "codigo": TRIBUTO_IVA,
                "descripcion": TRIBUTOS.get(TRIBUTO_IVA, ""),
                "valor": iva_val,
            }
        )
    monto_total_operacion = d2(Decimal(str(subtotal_ventas)) + Decimal(str(iva_val)))
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
        "condicionOperacion": orig_resumen.get("condicionOperacion", 1),
        "tributos": tributos_resumen,
        "montoTotalOperacion": monto_total_operacion,
    "totalLetras": monto_a_texto_sv(float(monto_total_operacion)),
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

    schema = catalogos.get_dte_schema("05")
    return sanitize_dte_payload(data, schema)

