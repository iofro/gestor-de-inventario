import json
import uuid
from decimal import Decimal as D

from db import DB
from dte import (
    generar_dte_json,
    d2,
    numero_a_letras,
    apply_schema_patch,
    _enviar_documento,
)
from utils import catalogos
from utils.catalogos import TRIBUTO_IVA, TRIBUTOS


def generar_nota_credito_json(db: DB, nota_id: int) -> dict:
    """Genera la estructura JSON para una Nota de Crédito Electrónica (NCE)."""

    row = db.cursor.execute("SELECT * FROM notas WHERE id=?", (nota_id,)).fetchone()
    if not row:
        raise ValueError("Nota no encontrada")

    nota = dict(row)
    if nota.get("tipo") != "credito":
        raise ValueError("La nota indicada no es de crédito")

    venta_id = nota.get("venta_id")
    venta = db.get_venta_by_id(venta_id) or {}

    # Datos base del DTE (identificación, emisor, receptor...)
    data = generar_dte_json(db, venta_id, tipo_dte="05")

    resumen_origen = data.get("resumen", {})
    total_origen = D(str(resumen_origen.get("montoTotalOperacion", 0)))

    # Determinar porcentaje a acreditar
    detalles_raw = nota.get("detalles")
    porcentaje = None
    if detalles_raw:
        try:
            detalles = json.loads(detalles_raw) if isinstance(detalles_raw, str) else detalles_raw
            porcentaje = D(str(detalles.get("porcentaje")))
        except Exception:
            porcentaje = None
    if porcentaje is not None:
        ratio = porcentaje / D(100)
    else:
        monto = D(str(nota.get("monto", 0)))
        total_venta = D(str(venta.get("total", 0))) or total_origen
        ratio = D("0") if total_venta == 0 else monto / total_venta
    ratio = max(D("0"), min(D("1"), ratio))
    pct = int((ratio * 100).quantize(D("1")))

    # Montos prorrateados
    total_gravada = d2(resumen_origen.get("totalGravada", 0)) * ratio
    total_exenta = d2(resumen_origen.get("totalExenta", 0)) * ratio
    total_no_suj = d2(resumen_origen.get("totalNoSuj", 0)) * ratio
    sub_total = total_gravada + total_exenta + total_no_suj

    iva_orig = D("0")
    for t in resumen_origen.get("tributos") or []:
        if isinstance(t, dict):
            if t.get("codigo") == TRIBUTO_IVA:
                iva_orig = D(str(t.get("valor")))
                break
        elif isinstance(t, str) and t == TRIBUTO_IVA:
            iva_orig = D(str(resumen_origen.get("totalIva", 0)))
            break
    iva = d2(iva_orig) * ratio
    monto_total_operacion = sub_total + iva

    resumen = {
        "totalNoSuj": float(total_no_suj),
        "totalExenta": float(total_exenta),
        "totalGravada": float(total_gravada),
        "subTotal": float(sub_total),
        "subTotalVentas": float(sub_total),
        "descuNoSuj": 0.0,
        "descuExenta": 0.0,
        "descuGravada": 0.0,
        "totalDescu": 0.0,
        "tributos": [] if total_gravada == 0 else [
            {
                "codigo": TRIBUTO_IVA,
                "descripcion": TRIBUTOS.get(TRIBUTO_IVA, ""),
                "valor": float(iva),
            }
        ],
        "ivaRete1": 0.0,
        "reteRenta": 0.0,
        "condicionOperacion": 1,
        "montoTotalOperacion": float(monto_total_operacion),
        "ivaPerci1": 0.0,
        "totalLetras": numero_a_letras(monto_total_operacion),
    }

    doc_rel_uuid = str(uuid.uuid4()).upper()
    items = []
    contador = 1
    categorias = [
        ("G", total_gravada, "operaciones gravadas", "ventaGravada"),
        ("E", total_exenta, "operaciones exentas", "ventaExenta"),
        ("N", total_no_suj, "operaciones no sujetas", "ventaNoSuj"),
    ]
    for sufijo, monto_cat, desc_cat, campo in categorias:
        if monto_cat <= 0:
            continue
        item = {
            "numItem": contador,
            "tipoItem": 1,
            "codigo": f"NC{pct}-{doc_rel_uuid[:8]}-{sufijo}",
            "descripcion": f"Nota de crédito {pct}% sobre {desc_cat} del CCF relacionado",
            "cantidad": 1,
            "uniMedida": 59,
            "precioUni": float(monto_cat),
            "montoDescu": 0.0,
            "ventaGravada": 0.0,
            "ventaExenta": 0.0,
            "ventaNoSuj": 0.0,
            "tributos": [TRIBUTO_IVA] if sufijo == "G" else [],
            "numeroDocumento": doc_rel_uuid,
            "codTributo": None,
        }
        item[campo] = float(monto_cat)
        items.append(item)
        contador += 1

    data["cuerpoDocumento"] = items
    data["resumen"] = resumen
    data["documentoRelacionado"] = [
        {
            "tipoDocumento": "03",
            "tipoGeneracion": 2,
            "numeroDocumento": doc_rel_uuid,
            "fechaEmision": venta.get("fecha"),
        }
    ]

    data["ventaTercero"] = None
    data["extension"] = None
    data["apendice"] = None

    return data


def generar_nota_debito_json(db: DB, nota_id: int) -> dict:
    """Genera la estructura JSON para una nota de débito."""
    row = db.cursor.execute("SELECT * FROM notas WHERE id=?", (nota_id,)).fetchone()
    if not row:
        raise ValueError("Nota no encontrada")
    nota = dict(row)
    if nota.get("tipo") != "debito":
        raise ValueError("La nota indicada no es de débito")

    venta_id = nota.get("venta_id")
    venta_row = db.cursor.execute(
        "SELECT cliente_id FROM ventas WHERE id=?", (venta_id,)
    ).fetchone()
    tipo_doc = "01"
    if venta_row:
        venta = dict(venta_row)
        if not db.get_venta_credito_fiscal(venta_id) and not venta.get("cliente_id"):
            tipo_doc = "03"
    data = generar_dte_json(db, venta_id, tipo_dte="06")
    data["documentoRelacionado"] = {
        "tipoDoc": tipo_doc,
        "numeroDocumento": data["identificacion"].get("numeroControl") or venta_id,
    }
    return data


def generar_nota_remision_json(db: DB, nota_id: int) -> dict:
    """Genera la estructura JSON para una nota de remisión."""
    row = db.cursor.execute("SELECT * FROM notas WHERE id=?", (nota_id,)).fetchone()
    if not row:
        raise ValueError("Nota no encontrada")
    nota = dict(row)
    if nota.get("tipo") != "remision":
        raise ValueError("La nota indicada no es de remisión")

    venta_id = nota.get("venta_id")
    venta_row = db.cursor.execute(
        "SELECT cliente_id FROM ventas WHERE id=?", (venta_id,)
    ).fetchone()
    tipo_doc = "01"
    if venta_row:
        venta = dict(venta_row)
        if not db.get_venta_credito_fiscal(venta_id) and not venta.get("cliente_id"):
            tipo_doc = "03"
    data = generar_dte_json(db, venta_id, tipo_dte="04")
    data["documentoRelacionado"] = {
        "tipoDoc": tipo_doc,
        "numeroDocumento": data["identificacion"].get("numeroControl") or venta_id,
    }
    return data


def enviar_nota_credito(db: DB, nota_id: int, modo: str = "normal") -> dict:
    """Genera y transmite una nota de crédito."""
    data = generar_nota_credito_json(db, nota_id)
    data = apply_schema_patch(data)
    schema = catalogos.get_dte_schema("05")
    # Validación omitida.
    # try:
    #     dte.validate_dte_json(data, db=db)
    # except Exception as exc:
    #     json_path = dte.save_dte_json(data)
    #     errors = dte._format_validation_errors(exc)
    #     raise dte.DTEValidationError(errors, json_path) from exc
    return _enviar_documento(db, nota_id, data, modo)


def enviar_nota_debito(db: DB, nota_id: int, modo: str = "normal") -> dict:
    """Genera y transmite una nota de débito."""
    data = generar_nota_debito_json(db, nota_id)
    data = apply_schema_patch(data)
    schema = catalogos.get_dte_schema("06")
    # Validación omitida.
    # try:
    #     dte.validate_dte_json(data, db=db)
    # except Exception as exc:
    #     json_path = dte.save_dte_json(data)
    #     errors = dte._format_validation_errors(exc)
    #     raise dte.DTEValidationError(errors, json_path) from exc
    return _enviar_documento(db, nota_id, data, modo)


def enviar_nota_remision(db: DB, nota_id: int, modo: str = "normal") -> dict:
    """Genera y transmite una nota de remisión."""
    data = generar_nota_remision_json(db, nota_id)
    data = apply_schema_patch(data)
    schema = catalogos.get_dte_schema("04")
    # Validación omitida.
    # try:
    #     dte.validate_dte_json(data, db=db)
    # except Exception as exc:
    #     json_path = dte.save_dte_json(data)
    #     errors = dte._format_validation_errors(exc)
    #     raise dte.DTEValidationError(errors, json_path) from exc
    return _enviar_documento(db, nota_id, data, modo)

