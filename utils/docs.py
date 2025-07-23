import os
import re
import json
from datetime import datetime

# Base path is repository root two levels up from this file
BASE_DIR = os.path.dirname(os.path.dirname(__file__))

FOLDERS = {
    'ConsumidorFinal': os.path.join(BASE_DIR, 'facturas_consumidor_final'),
    'CreditoFiscal': os.path.join(BASE_DIR, 'facturas_credito_fiscal'),
    'Ticket': os.path.join(BASE_DIR, 'tickets'),
    'NotaDebito': os.path.join(BASE_DIR, 'notas_debito'),
    'NotaCredito': os.path.join(BASE_DIR, 'notas_credito'),
}

TEMPLATE_PATH = os.path.join(BASE_DIR, 'formato_factura.json')


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


def build_invoice_json(venta, cliente, detalles, template_path=TEMPLATE_PATH):
    """Create an invoice JSON following the template structure."""
    with open(template_path, 'r', encoding='utf-8') as fh:
        data = json.load(fh)

    ident = data.get('identificacion', {})
    if venta.get('numero_control'):
        ident['numeroControl'] = venta['numero_control']
    if venta.get('codigo_generacion'):
        ident['codigoGeneracion'] = venta['codigo_generacion']
    if venta.get('fecha'):
        ident['fecEmi'] = venta['fecha']
    data['identificacion'] = ident

    rec = data.get('receptor', {})
    if cliente:
        if cliente.get('nombre'):
            rec['nombre'] = cliente['nombre']
        if cliente.get('direccion'):
            rec['direccion'] = cliente['direccion']
        if cliente.get('nit'):
            rec['nit'] = cliente['nit']
    data['receptor'] = rec

    cuerpo = []
    for idx, det in enumerate(detalles or [], 1):
        cuerpo.append({
            'numItem': idx,
            'descripcion': det.get('descripcion'),
            'cantidad': det.get('cantidad'),
            'precioUnitario': det.get('precio_unitario'),
        })
    data['cuerpoDocumento'] = cuerpo

    resumen = data.get('resumen', {})
    if venta.get('total') is not None:
        resumen['totalPagar'] = venta['total']
    if venta.get('subtotal') is not None:
        resumen['subTotalVentas'] = venta['subtotal']
        resumen['subTotal'] = venta['subtotal']
    if venta.get('total_letras'):
        resumen['totalLetras'] = venta['total_letras']
    data['resumen'] = resumen

    return data


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
