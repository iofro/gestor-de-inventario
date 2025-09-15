# coding: utf-8
"""Generación de Nota de Débito Electrónica (NDE).

Este módulo construye la estructura JSON requerida por el Ministerio de
Hacienda de El Salvador para una Nota de Débito Electrónica (tipoDte ``06``).
Se genera a partir de un DTE de origen y permite acreditar montos o
proporciones del documento original.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
import copy
import json
import os
import re
from typing import Optional

from db import DB
from dte import (
    DTE_VERSIONES,
    generar_cabecera_dte_data,
    sanitize_dte_payload,
    d4,
    _origen_aceptado_en_mh,
)
from utils import catalogos
from utils.catalogos import TRIBUTO_IVA, TRIBUTOS
from utils.fecha import TZ_EL_SALVADOR, fecha_emision_hoy_str
from utils.monto import d2, monto_a_texto_sv
from utils.sanitize import limpiar_documentos


def _is_uuid(s: str) -> bool:
    return bool(
        re.fullmatch(r"[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}", s.upper())
    )


def _is_nc(s: str) -> bool:
    return str(s).startswith("DTE-")


def _build_documento_relacionado(origen_ident: dict) -> tuple[list[dict], str]:
    uuid_rel = str(origen_ident.get("codigoGeneracion", "")).upper()
    nc_rel = origen_ident.get("numeroControl")
    fec_rel = origen_ident.get("fecEmi")
    tipo_generacion = origen_ident.get("tipoGeneracion")
    numero_conf = origen_ident.get("numeroDocumento")
    if tipo_generacion is None and numero_conf:
        if _is_uuid(str(numero_conf)):
            tipo_generacion = 2
        elif _is_nc(str(numero_conf)):
            tipo_generacion = 1
        else:
            raise ValueError("numeroDocumento inválido para documentoRelacionado")
    if tipo_generacion is None:
        tipo_generacion = 2
    if tipo_generacion == 2:
        numero_rel = uuid_rel
    elif tipo_generacion == 1:
        numero_rel = nc_rel
    else:
        raise ValueError("tipoGeneracion inválido para documentoRelacionado")
    doc_rel = [
        {
            "tipoDocumento": origen_ident.get("tipoDte"),
            "tipoGeneracion": tipo_generacion,
            "numeroDocumento": numero_rel,
            "fechaEmision": fec_rel,
        }
    ]
    return doc_rel, numero_rel


def generar_nde_desde_nota(db: DB, nota_id: int, *, ambiente: str = "00") -> dict:
    """Genera una NDE basada en la nota registrada en ``notas``."""
    row = db.cursor.execute("SELECT * FROM notas WHERE id=?", (nota_id,)).fetchone()
    if not row:
        raise ValueError("Nota no encontrada")
    nota = dict(row)
    if nota.get("tipo") != "debito":
        raise ValueError("La nota indicada no es de débito")

    venta_id = nota.get("venta_id")
    venta_row = db.cursor.execute(
        "SELECT extra FROM ventas WHERE id=?", (venta_id,),
    ).fetchone()
    if not venta_row:
        raise ValueError("Venta no encontrada")

    extra = {}
    if venta_row["extra"]:
        try:
            extra = json.loads(venta_row["extra"])
        except Exception:
            extra = {}
    dte_path = extra.get("dteJsonPath")
    if not dte_path or not os.path.exists(dte_path):
        raise ValueError("DTE base no encontrado")
    with open(dte_path, "r", encoding="utf-8") as fh:
        dte_origen = json.load(fh)

    if not _origen_aceptado_en_mh(db, dte_origen.get("identificacion", {})):
        raise ValueError(
            "El documento relacionado aún no está registrado en MH. Transmítelo y espera acuse antes de emitir la nota."
        )

    detalles = None
    if nota.get("detalles"):
        try:
            detalles = json.loads(nota["detalles"])
        except Exception:
            detalles = None

    return generar_nde_desde_dte(
        db,
        dte_origen,
        detalles,
        nota.get("monto"),
        nota.get("motivo"),
        ambiente=ambiente,
    )


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
    sello = dte_origen.get("selloRecibido") or dte_origen.get("extra", {}).get("selloRecibido")
    if not sello:
        raise ValueError(
            "La factura base no tiene selloRecibido. No puedes referenciarla todavía."
        )
    if not _origen_aceptado_en_mh(db, dte_origen.get("identificacion", {})):
        raise ValueError(
            "El documento relacionado aún no está registrado en MH. Transmítelo y espera acuse antes de emitir la nota."
        )
    cabecera = generar_cabecera_dte_data(1, 1, "06", db, ambiente=ambiente)
    now = datetime.now(TZ_EL_SALVADOR)
    identificacion = {
        "version": DTE_VERSIONES["06"],
        "ambiente": ambiente,
        "tipoDte": "06",
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
    doc_rel, numero_rel = _build_documento_relacionado(origen_ident)

    emisor = copy.deepcopy(dte_origen.get("emisor", {}))
    receptor = copy.deepcopy(dte_origen.get("receptor", {}))
    receptor.setdefault("nombreComercial", "")
    if not receptor["nombreComercial"]:
        receptor["nombreComercial"] = receptor.get("nombre", "")
    nit_val = str(receptor.get("nit") or "")
    num_doc = str(receptor.get("numDocumento") or "")
    if not nit_val:
        if num_doc.isdigit() and len(num_doc) == 14 and num_doc != "00000000000000":
            receptor["nit"] = num_doc
        else:
            receptor.pop("nit", None)
    else:
        receptor["nit"] = nit_val
    limpiar_documentos(emisor)
    limpiar_documentos(receptor)
    if "nit" in receptor:
        receptor["nit"] = str(receptor["nit"])
    receptor["nombreComercial"] = str(
        receptor.get("nombreComercial", "")
    )

    orig_resumen = dte_origen.get("resumen", {})
    items: list[dict] = []
    uuid_origen = str(origen_ident.get("codigoGeneracion", "")).upper()
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
                    "numeroDocumento": numero_rel,
                    "codTributo": None,
                }
            )
            num += 1

        total_grav = d4(total_grav)
        total_exenta = d4(total_exenta)
        total_nosuj = d4(total_nosuj)
        subtotal_ventas_q4 = total_grav + total_exenta + total_nosuj
        subtotal_ventas = d2(subtotal_ventas_q4)

        user_total = Decimal(str(monto)) if monto is not None else None
        if user_total is not None and user_total >= subtotal_ventas:
            monto_total = d2(user_total)
            iva_val = d2(monto_total - subtotal_ventas)
        else:
            monto_total = d2(
                total_grav * Decimal("1.13") + total_exenta + total_nosuj
            )
            iva_val = d2(monto_total - subtotal_ventas)

        total_grav = d2(total_grav)
        total_exenta = d2(total_exenta)
        total_nosuj = d2(total_nosuj)
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
                    "numeroDocumento": numero_rel,
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
                    "numeroDocumento": numero_rel,
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
                    "numeroDocumento": numero_rel,
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
        "totalNoSuj": d2(total_nosuj),
        "totalExenta": d2(total_exenta),
        "totalGravada": d2(total_grav),
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

    schema = catalogos.get_dte_schema("06")
    return sanitize_dte_payload(data, schema)


__all__ = ["generar_nde_desde_dte", "generar_nde_desde_nota"]
