import json
import os
import re
from datetime import datetime

# Base path is repository root two levels up from this file
BASE_DIR = os.path.dirname(os.path.dirname(__file__))

FOLDERS = {
    'ConsumidorFinal': os.path.join(BASE_DIR, 'facturas_consumidor_final'),
    'CreditoFiscal': os.path.join(BASE_DIR, 'facturas_credito_fiscal'),
    'Ticket': os.path.join(BASE_DIR, 'tickets'),
    'NotaDebito': os.path.join(BASE_DIR, 'notas_debito'),
    'NotaCredito': os.path.join(BASE_DIR, 'notas_credito'),
    'NotaRemision': os.path.join(BASE_DIR, 'notas_remision'),
}

TEMPLATE_PATH = os.path.join(BASE_DIR, 'formato_factura.json')

# Código de tributo IVA según Hacienda
TRIBUTO_IVA = "20"


def sanitize_filename(value: str) -> str:
    """Return a filesystem friendly version of ``value``."""
    if not value:
        return ''
    sanitized = re.sub(r'[^A-Za-z0-9]+', '_', value)
    return sanitized.strip('_')


def generate_document_name(date, cliente, identifier, doc_type) -> str:
    """Return the base filename for a document."""
    if isinstance(date, datetime):
        d = date
    else:
        try:
            d = datetime.strptime(str(date)[:10], '%Y-%m-%d')
        except Exception:
            d = datetime.now()
    date_str = d.strftime('%Y%m%d')
    parts = [date_str, sanitize_filename(cliente), str(identifier), sanitize_filename(doc_type)]
    parts = [p for p in parts if p]
    return '_'.join(parts)


def get_document_paths(date, cliente, identifier, doc_type, root=None):
    """Return PDF and JSON paths for the given document."""
    base = root or BASE_DIR
    folder = FOLDERS.get(doc_type)
    if root:
        # when custom root is provided, mirror folder names inside it
        name = os.path.basename(folder)
        folder = os.path.join(root, name)
    os.makedirs(folder, exist_ok=True)
    base_name = generate_document_name(date, cliente, identifier, doc_type)
    pdf_path = os.path.join(folder, base_name + '.pdf')
    json_path = os.path.join(folder, base_name + '.json')
    return pdf_path, json_path


def _remove_none(value):
    """Recursively remove keys with ``None`` values from ``value``."""
    if isinstance(value, dict):
        return {
            k: _remove_none(v)
            for k, v in value.items()
            if v is not None
        }
    if isinstance(value, list):
        return [_remove_none(v) for v in value if v is not None]
    return value


def _validate_identificacion(identificacion: dict) -> None:
    """Ensure ``identificacion`` has mandatory fields."""
    required = [
        "ambiente",
        "version",
        "tipoDte",
        "codigoGeneracion",
        "numeroControl",
    ]
    if not isinstance(identificacion, dict):
        raise ValueError("identificacion requerida")
    for key in required:
        if identificacion.get(key) in (None, ""):
            raise ValueError(f"identificacion.{key} requerido")


def _validate_parties(emisor: dict, receptor: dict) -> None:
    """Validate presence of parties and their addresses."""
    if not isinstance(emisor, dict) or not emisor:
        raise ValueError("emisor requerido")
    direccion_emi = emisor.get("direccion")
    if not isinstance(direccion_emi, dict):
        raise ValueError("emisor.direccion requerido")
    if not direccion_emi.get("departamento") or not direccion_emi.get("municipio"):
        raise ValueError("emisor.direccion incompleta")

    if not isinstance(receptor, dict):
        raise ValueError("receptor requerido")
    direccion_rec = receptor.get("direccion")
    if direccion_rec:
        if not direccion_rec.get("departamento") or not direccion_rec.get("municipio"):
            raise ValueError("receptor.direccion incompleta")


def _validate_items(items: list) -> None:
    if not isinstance(items, list) or not items:
        raise ValueError("items requeridos")
    for idx, item in enumerate(items, 1):
        cantidad = item.get("cantidad")
        try:
            cantidad_val = float(cantidad)
        except (TypeError, ValueError):
            raise ValueError(f"item {idx}: cantidad numerica requerida")
        if cantidad_val <= 0:
            raise ValueError(f"item {idx}: cantidad>0 requerido")

        precio = item.get("precioUnitario")
        try:
            float(precio)
        except (TypeError, ValueError):
            raise ValueError(f"item {idx}: precioUnitario numerico requerido")

        tributos = item.get("tributos")
        if tributos is not None and not tributos:
            raise ValueError(f"item {idx}: tributos vacio")
        if tributos:
            for t in tributos:
                if t.get("monto") is None:
                    raise ValueError(f"item {idx}: tributo.monto requerido")
                try:
                    float(t.get("monto"))
                except (TypeError, ValueError):
                    raise ValueError(f"item {idx}: tributo.monto numerico requerido")


def _map_items(items: list) -> list:
    cuerpo = []
    for idx, src in enumerate(items, 1):
        cantidad = round(float(src.get("cantidad", 0)), 2)
        precio = round(float(src.get("precioUnitario", 0)), 2)
        mapped = {
            "numItem": idx,
            "descripcion": src.get("descripcion"),
            "cantidad": cantidad,
            "precioUnitario": precio,
            "montoTotal": round(cantidad * precio, 2),
        }
        tributos = src.get("tributos") or []
        if tributos:
            mapped["tributos"] = []
            for t in tributos:
                codigo = str(t.get("codigo") or TRIBUTO_IVA)
                monto = round(float(t.get("monto", 0)), 2)
                mapped["tributos"].append(
                    {
                        "codigo": codigo,
                        "monto": monto,
                        "descripcion": t.get("descripcion"),
                    }
                )
        cuerpo.append(_remove_none(mapped))
    return cuerpo


def _make_resumen(cuerpo: list, extras: dict | None = None) -> dict:
    subtotal = sum(float(item.get("montoTotal", 0)) for item in cuerpo)
    tributos_totales = {}
    for item in cuerpo:
        for t in item.get("tributos", []):
            codigo = str(t.get("codigo") or TRIBUTO_IVA)
            tributos_totales[codigo] = tributos_totales.get(codigo, 0) + float(
                t.get("monto", 0)
            )
    tributos_list = [
        {"codigo": c, "monto": round(m, 2)} for c, m in tributos_totales.items()
    ]
    total_tributos = sum(t["monto"] for t in tributos_list)
    total_pagar = round(subtotal + total_tributos, 2)
    resumen = {
        "subTotalVentas": round(subtotal, 2),
        "totalPagar": total_pagar,
    }
    if tributos_list:
        resumen["tributos"] = tributos_list
    if extras:
        resumen.update({k: v for k, v in extras.items() if v is not None})

    calc_total = round(
        resumen.get("subTotalVentas", 0)
        + sum(t.get("monto", 0) for t in resumen.get("tributos", [])),
        2,
    )
    if calc_total != round(resumen.get("totalPagar", 0), 2):
        raise ValueError("Totales incoherentes")
    return resumen


def build_invoice_json(*, identificacion, emisor, receptor, items, extras=None):
    """Return a validated invoice ready for signing."""
    _validate_identificacion(identificacion)
    _validate_parties(emisor, receptor)
    _validate_items(items)

    cuerpo = _map_items(items)
    extras = extras or {}
    resumen = _make_resumen(cuerpo, extras.get("resumen"))

    dte = {
        "identificacion": identificacion,
        "emisor": emisor,
        "receptor": receptor,
        "cuerpoDocumento": cuerpo,
        "resumen": resumen,
    }
    if extras.get("documentoRelacionado"):
        dte["documentoRelacionado"] = extras["documentoRelacionado"]
    return _remove_none(dte)


def list_documents(root=None):
    """Return a list of paired PDF/JSON documents found in folders."""
    base = root or BASE_DIR
    result = []
    for doc_type, folder in FOLDERS.items():
        if root:
            folder = os.path.join(base, os.path.basename(folder))
        if not os.path.isdir(folder):
            continue
        pairs = {}
        for fname in os.listdir(folder):
            base_name, ext = os.path.splitext(fname)
            path = os.path.join(folder, fname)
            if ext.lower() == '.pdf':
                pairs.setdefault(base_name, {})['pdf'] = path
            elif ext.lower() == '.json':
                pairs.setdefault(base_name, {})['json'] = path
        for name, paths in pairs.items():
            if 'pdf' in paths and 'json' in paths:
                result.append({'tipo': doc_type, 'pdf': paths['pdf'], 'json': paths['json']})
    return result
