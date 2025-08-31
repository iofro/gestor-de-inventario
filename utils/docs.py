import json
import os
import re
from datetime import datetime
from decimal import Decimal

from jsonschema import Draft7Validator, ValidationError

from dte import _map_departamento, _map_municipio

# Base path is repository root two levels up from this file
BASE_DIR = os.path.dirname(os.path.dirname(__file__))
CONFIG_NEGOCIO_PATH = os.path.join(BASE_DIR, "config_negocio.json")
SCHEMA_FC_PATH = os.path.join(BASE_DIR, "svfe-json-schemas", "fe-fc-v1.json")

FOLDERS = {
    'ConsumidorFinal': os.path.join(BASE_DIR, 'facturas_consumidor_final'),
    'CreditoFiscal': os.path.join(BASE_DIR, 'facturas_credito_fiscal'),
    'Ticket': os.path.join(BASE_DIR, 'tickets'),
    'NotaDebito': os.path.join(BASE_DIR, 'notas_debito'),
    'NotaCredito': os.path.join(BASE_DIR, 'notas_credito'),
    'NotaRemision': os.path.join(BASE_DIR, 'notas_remision'),
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


def build_invoice_json(venta, cliente, detalles, template_path=TEMPLATE_PATH, validate=True):
    """Create an invoice JSON following the template structure."""
    try:
        with open(template_path, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
    except FileNotFoundError:
        data = {
            'identificacion': {},
            'receptor': {},
            'cuerpoDocumento': [],
            'resumen': {},
        }

    ident = data.get('identificacion', {})
    if venta.get('numero_control'):
        ident['numeroControl'] = venta['numero_control']
    if venta.get('codigo_generacion'):
        ident['codigoGeneracion'] = venta['codigo_generacion']
    if venta.get('fecha'):
        try:
            dt = datetime.fromisoformat(str(venta['fecha']))
            ident['fecEmi'] = dt.strftime('%Y-%m-%d')
            ident['horEmi'] = dt.strftime('%H:%M:%S')
        except ValueError:
            ident['fecEmi'] = str(venta['fecha'])[:10]
            ident['horEmi'] = str(venta.get('hora') or '00:00:00')[:8]
    ident.setdefault('version', 1)
    ident.setdefault('ambiente', venta.get('ambiente', '00'))
    ident.setdefault('tipoMoneda', 'USD')
    ident.setdefault('tipoDte', venta.get('tipo_dte', '01'))
    if venta.get('tipo_operacion') is not None:
        ident['tipoOperacion'] = venta['tipo_operacion']
        ident['tipoModelo'] = 2 if venta['tipo_operacion'] == 2 else 1
    if venta.get('tipo_contingencia') is not None:
        ident['tipoContingencia'] = venta['tipo_contingencia']
    if venta.get('motivo_contin') is not None:
        ident['motivoContin'] = venta['motivo_contin']
    data['identificacion'] = ident

    # Populate emisor from configuration if available
    emisor = data.get('emisor', {})
    try:
        with open(CONFIG_NEGOCIO_PATH, 'r', encoding='utf-8') as fh:
            cfg = json.load(fh)
        cfg_emisor = cfg.get('emisor') or {
            k: v for k, v in cfg.items()
            if k not in ('ambiente', 'pruebas', 'produccion')
        }
        if isinstance(cfg_emisor, dict):
            emisor.update(cfg_emisor)
    except Exception:
        pass
    data['emisor'] = emisor

    rec = data.get('receptor', {})
    if cliente:
        if cliente.get('nombre'):
            rec['nombre'] = cliente['nombre']
        if cliente.get('direccion'):
            rec['direccion'] = cliente['direccion']
        if cliente.get('nit'):
            rec['nit'] = cliente['nit']
        if cliente.get('tipoDocumento'):
            rec['tipoDocumento'] = cliente['tipoDocumento']
        if cliente.get('numDocumento'):
            rec['numDocumento'] = cliente['numDocumento']
        if cliente.get('departamento'):
            rec['departamento'] = _map_departamento(cliente['departamento'])
        if cliente.get('municipio'):
            rec['municipio'] = _map_municipio(
                cliente['municipio'], cliente.get('departamento')
            )
    data['receptor'] = rec

    cuerpo = []
    for idx, det in enumerate(detalles or [], 1):
        cantidad = det.get('cantidad') or 0
        precio = det.get('precio_unitario') or 0
        venta_gravada = det.get('ventaGravada') or det.get('venta_gravada')
        if venta_gravada is None:
            venta_gravada = float(Decimal(str(cantidad)) * Decimal(str(precio)))
        iva_item = det.get('ivaItem') or det.get('iva_item')
        if iva_item is None:
            base = Decimal(str(venta_gravada)) / Decimal('1.13') if venta_gravada else Decimal('0')
            iva_item = float(Decimal(str(venta_gravada)) - base)
        item = {
            'numItem': idx,
            'tipoItem': det.get('tipoItem') or 1,
            'numeroDocumento': det.get('numeroDocumento'),
            'cantidad': cantidad,
            'codigo': det.get('codigo'),
            'codTributo': det.get('codTributo'),
            'uniMedida': det.get('uniMedida') or 59,
            'descripcion': det.get('descripcion'),
            'precioUni': precio,
            'montoDescu': det.get('montoDescu') or 0,
            'ventaNoSuj': det.get('ventaNoSuj') or 0,
            'ventaExenta': det.get('ventaExenta') or 0,
            'ventaGravada': venta_gravada or 0,
            'tributos': det.get('tributos') or [],
            'psv': det.get('psv') or 0,
            'noGravado': det.get('noGravado') or 0,
            'ivaItem': iva_item or 0,
        }
        cuerpo.append(item)
    data['cuerpoDocumento'] = cuerpo

    resumen = data.get('resumen', {})
    total = venta.get('total')
    if total is not None:
        resumen['totalPagar'] = total
    subtotal = venta.get('subtotal')
    if subtotal is not None:
        resumen['subTotalVentas'] = subtotal
        resumen['subTotal'] = subtotal
    if venta.get('total_letras'):
        resumen['totalLetras'] = venta['total_letras']

    gravada_sum = sum(Decimal(str(i.get('ventaGravada') or 0)) for i in cuerpo)
    iva_sum = sum(Decimal(str(i.get('ivaItem') or 0)) for i in cuerpo)

    resumen.setdefault('totalNoSuj', 0)
    resumen.setdefault('totalExenta', 0)
    resumen.setdefault('totalGravada', float(gravada_sum))
    resumen.setdefault('subTotalVentas', float(gravada_sum))
    resumen.setdefault('descuNoSuj', 0)
    resumen.setdefault('descuExenta', 0)
    resumen.setdefault('descuGravada', 0)
    resumen.setdefault('porcentajeDescuento', 0)
    resumen.setdefault('totalDescu', 0)
    resumen.setdefault('tributos', None)
    resumen.setdefault('subTotal', float(gravada_sum))
    resumen.setdefault('ivaRete1', 0)
    resumen.setdefault('reteRenta', 0)
    resumen.setdefault('montoTotalOperacion', float(gravada_sum))
    resumen.setdefault('totalNoGravado', 0)
    resumen.setdefault('totalPagar', float(resumen.get('totalPagar', gravada_sum)))
    resumen.setdefault('totalLetras', '')
    resumen.setdefault('totalIva', float(iva_sum))
    resumen.setdefault('saldoFavor', 0)
    resumen.setdefault('condicionOperacion', venta.get('condicion_operacion', 1))
    pagos = resumen.get('pagos')
    if not pagos:
        pagos = [{
            'codigo': '01',
            'montoPago': resumen.get('totalPagar', 0),
            'referencia': None,
            'plazo': None,
            'periodo': None,
        }]
    resumen['pagos'] = pagos
    resumen.setdefault('numPagoElectronico', None)
    data['resumen'] = resumen

    # Normalise emisor address codes if present
    emisor = data.get('emisor')
    if isinstance(emisor, dict):
        dir_emi = emisor.get('direccion')
        if isinstance(dir_emi, dict):
            dep = dir_emi.get('departamento')
            dir_emi['departamento'] = _map_departamento(dep)
            dir_emi['municipio'] = _map_municipio(
                dir_emi.get('municipio'), dep
            )
            emisor['direccion'] = dir_emi
        data['emisor'] = emisor

    if validate and cuerpo:
        try:
            with open(SCHEMA_FC_PATH, 'r', encoding='utf-8') as fh:
                schema = json.load(fh)
            Draft7Validator(schema).validate(data)
        except ValidationError as exc:
            raise ValueError(f"DTE inválido: {exc.message}") from exc

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
