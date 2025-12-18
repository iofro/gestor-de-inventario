import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping

from dte import _map_departamento, _map_municipio, _build_receptor_direccion
from paths import (
    TICKETS_OUTPUT_DIR,
    get_canonical_dte_dir,
    user_data_path,
)
from utils import resource_path
from utils import versioned_dte
from utils.stable_json import save_file, stable_stringify

logger = logging.getLogger(__name__)

BASE_DIR = user_data_path()

_CANONICAL_TYPES = {
    "ConsumidorFinal": "ConsumidorFinal",
    "CreditoFiscal": "CreditoFiscal",
    "NotaDebito": "NotaDebito",
    "NotaCredito": "NotaCredito",
    "NotaRemision": "NotaRemision",
    "SujetoExcluido": "SujetoExcluido",
}

TEMPLATE_PATH = resource_path('formato_factura.json')


def _canonical_folder_name(doc_type: str | None) -> str:
    if not doc_type:
        return "documentos"
    canonical = _CANONICAL_TYPES.get(doc_type)
    if canonical:
        return get_canonical_dte_dir(canonical).name
    if doc_type == "Ticket":
        return Path(TICKETS_OUTPUT_DIR).name
    return sanitize_filename(doc_type or "documentos")


def _resolve_folder(doc_type: str | None, *, root: str | os.PathLike | None) -> Path:
    if root:
        base = Path(root)
        name = _canonical_folder_name(doc_type)
        folder = base / name
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    canonical = _CANONICAL_TYPES.get(doc_type or "")
    if canonical:
        return get_canonical_dte_dir(canonical)
    if doc_type == "Ticket":
        folder = Path(TICKETS_OUTPUT_DIR)
    else:
        folder = Path(BASE_DIR) / sanitize_filename(doc_type or "documentos")
    folder.mkdir(parents=True, exist_ok=True)
    return folder


# ---------------------------------------------------------------------------
# Helpers for client-facing JSON payloads
# ---------------------------------------------------------------------------


def _normalize_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    try:
        text = str(value)
    except Exception:
        return None
    text = text.strip()
    if not text:
        return None
    return text


def _normalize_sello(value: Any) -> str | None:
    sello = _normalize_optional_str(value)
    if not sello:
        return None
    if re.fullmatch(r"[0-9A-Fa-f]{40}", sello):
        return sello.upper()
    return sello


def build_client_json_payload(
    dte_payload: Mapping[str, Any] | None,
    *,
    firma: str | None = None,
    sello: str | None = None,
    existing_payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a client-facing JSON structure containing the signed DTE.

    The resulting mapping always exposes the complete DTE under ``dteJson`` and,
    when available, the electronic signature (``firmaElectronica``) and the
    reception seal (``selloRecibido``).
    """

    if isinstance(dte_payload, Mapping):
        dte_json = dict(dte_payload)
    else:
        dte_json = {}

    # Ensure sensitive fields live outside the embedded DTE payload.
    dte_json.pop("firmaElectronica", None)
    dte_json.pop("selloRecibido", None)

    firma_norm = _normalize_optional_str(firma)
    sello_norm = _normalize_sello(sello)

    if existing_payload and not firma_norm and isinstance(existing_payload, Mapping):
        firma_norm = _normalize_optional_str(existing_payload.get("firmaElectronica"))

    if existing_payload and not sello_norm and isinstance(existing_payload, Mapping):
        sello_norm = _normalize_sello(
            existing_payload.get("selloRecibido")
            or getattr(existing_payload.get("respuesta", {}), "get", lambda *_: None)(
                "selloRecibido"
            )
        )

    client_payload: dict[str, Any] = {"dteJson": dte_json}
    if firma_norm:
        client_payload["firmaElectronica"] = firma_norm
    if sello_norm:
        client_payload["selloRecibido"] = sello_norm

    return client_payload


def persist_client_json(
    json_path: str | os.PathLike,
    dte_payload: Mapping[str, Any] | None,
    *,
    firma: str | None = None,
    sello: str | None = None,
    existing_payload: Mapping[str, Any] | None = None,
) -> Path:
    """Write a client-facing JSON representation and duplicate it as a backup.

    The JSON is written to ``json_path`` and to a sibling folder named
    ``copia de seguridad``. Both files use the same filename so they can be
    easily correlated.
    """

    target = Path(json_path)
    formatted = build_client_json_payload(
        dte_payload, firma=firma, sello=sello, existing_payload=existing_payload
    )
    content = stable_stringify(formatted, indent=2)

    target.parent.mkdir(parents=True, exist_ok=True)
    save_file(os.fspath(target), content)

    backup_dir = target.parent / "copia de seguridad"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / target.name
    save_file(os.fspath(backup_path), content)

    return target


def sync_client_json_with_canonical(
    json_path: str | os.PathLike,
    *,
    codigo: str | None = None,
    sello: str | None = None,
    base_dir: str | os.PathLike | None = None,
) -> tuple[str | None, str | None]:
    """Ensure ``json_path`` mirrors the canonical DTE payload stored by código.

    The helper loads the canonical ``documento.json`` tracked in the versioned
    storage (``versioned_dte``) and rebuilds the client-facing JSON keeping the
    current ``firmaElectronica`` and ``selloRecibido`` values when available.

    Returns a tuple ``(codigo_generacion, sello_recibido)`` with the normalized
    identifiers that ended up persisted.  When the canonical payload is not
    available the function simply validates the provided metadata and leaves the
    file untouched.
    """

    try:
        json_file = Path(json_path)
    except TypeError:
        return (None, None)

    codigo_norm = (codigo or "").strip().upper()
    sello_norm = _normalize_sello(sello)

    existing_payload: Mapping[str, Any] | None = None
    try:
        if json_file.exists():
            with json_file.open("r", encoding="utf-8") as fh:
                loaded = json.load(fh)
            if isinstance(loaded, Mapping):
                existing_payload = loaded
                if not sello_norm:
                    sello_norm = _normalize_sello(loaded.get("selloRecibido"))
                    if not sello_norm:
                        respuesta = loaded.get("respuesta")
                        if isinstance(respuesta, Mapping):
                            sello_norm = _normalize_sello(respuesta.get("selloRecibido"))
    except Exception:
        existing_payload = None

    firma_actual = None
    if isinstance(existing_payload, Mapping):
        firma_actual = _normalize_optional_str(existing_payload.get("firmaElectronica"))

    canonical_payload: Mapping[str, Any] | None = None
    if codigo_norm:
        try:
            version_dir = versioned_dte.resolve_version_dir(base_dir, codigo_norm)
        except Exception:
            version_dir = None
        if version_dir:
            canonical_path = Path(version_dir) / "documento.json"
            try:
                with canonical_path.open("r", encoding="utf-8") as fh:
                    loaded = json.load(fh)
                if isinstance(loaded, Mapping):
                    canonical_payload = loaded
            except Exception:
                canonical_payload = None

    if canonical_payload is not None:
        ident = canonical_payload.get("identificacion") or canonical_payload.get("identificador")
        if isinstance(ident, Mapping):
            canon_code = (ident.get("codigoGeneracion") or "").strip().upper()
            if canon_code:
                codigo_norm = canon_code
    elif isinstance(existing_payload, Mapping):
        raw_payload = existing_payload.get("dteJson")
        if isinstance(raw_payload, Mapping):
            canonical_payload = raw_payload
        elif isinstance(existing_payload, Mapping):
            canonical_payload = existing_payload

    if canonical_payload is None:
        return (codigo_norm or None, sello_norm or None)

    payload_copy = dict(canonical_payload)
    ident = payload_copy.get("identificacion") or payload_copy.get("identificador") or {}
    if not isinstance(ident, Mapping):
        ident = {}
    ident_copy = dict(ident)
    if codigo_norm:
        ident_copy["codigoGeneracion"] = codigo_norm
    payload_copy["identificacion"] = ident_copy
    payload_copy.pop("identificador", None)

    try:
        persist_client_json(
            json_file,
            payload_copy,
            firma=firma_actual,
            sello=sello_norm,
            existing_payload=existing_payload,
        )
    except Exception:
        logger.exception("No se pudo sincronizar JSON con la versión canónica %s", json_file)

    return (codigo_norm or None, sello_norm or None)

def write_pdf_atomically(
    destination: os.PathLike | str,
    render: Callable[[Path], None],
) -> Path:
    """Render a PDF to ``destination`` atomically.

    ``render`` receives a :class:`Path` pointing to a temporary location where
    it should persist the PDF contents.  The helper ensures the destination is
    created via ``Path.replace`` to avoid partially written files.  Any
    failure is logged and re-raised so callers can react accordingly.
    """

    dest_path = Path(os.fspath(destination))
    parent = dest_path.parent
    parent.mkdir(parents=True, exist_ok=True)
    parent_exists = parent.exists()
    parent_writable = os.access(parent, os.W_OK)
    logger.info(
        "Validando carpeta destino %s (existe=%s writable=%s)",
        parent,
        parent_exists,
        parent_writable,
    )
    if not parent_exists:
        raise FileNotFoundError(f"Directorio destino inexistente: {parent}")
    if not parent_writable:
        raise PermissionError(f"No hay permisos de escritura en {parent}")
    tmp_path = dest_path.with_suffix(dest_path.suffix + ".tmp")
    try:
        logger.info("Escribiendo PDF temporal %s (destino final %s)", tmp_path, dest_path)
        logger.info(
            "TMP path parent %s existe=%s writable=%s",
            tmp_path.parent,
            tmp_path.parent.exists(),
            os.access(tmp_path.parent, os.W_OK),
        )
        render(tmp_path)
        if not tmp_path.exists():
            raise IOError(f"No se generó PDF temporal en {tmp_path}")
        tmp_size = tmp_path.stat().st_size
        if tmp_size <= 0:
            raise IOError(f"PDF temporal vacío en {tmp_path}")
        logger.info("PDF temporal creado en %s (%s bytes)", tmp_path, tmp_size)
        logger.info("Reemplazando %s con %s", dest_path, tmp_path)
        tmp_path.replace(dest_path)
        if not dest_path.exists():
            raise IOError(f"No se pudo mover PDF final a {dest_path}")
        final_size = dest_path.stat().st_size
        if final_size <= 0:
            raise IOError(f"PDF final vacío en {dest_path}")
        logger.info("PDF final escrito en %s (%s bytes)", dest_path, final_size)

        return dest_path
    except Exception as exc:
        logger.error("No se pudo escribir PDF en %s: %s", dest_path, exc)
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass
        raise


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

    folder = _resolve_folder(doc_type, root=root)
    base_name = generate_document_name(date, cliente, identifier, doc_type)
    pdf_path = folder / f"{base_name}.pdf"
    json_path = folder / f"{base_name}.json"
    return str(pdf_path), str(json_path)


def get_dte_document_paths(fecha, empresa, numero_control, doc_type, root=None):
    """Return paths ensuring MH-required naming for DTE notes."""
    folder = _resolve_folder(doc_type, root=root)
    if isinstance(fecha, datetime):
        d = fecha
    else:
        try:
            d = datetime.strptime(str(fecha)[:10], '%Y-%m-%d')
        except Exception:
            d = datetime.now()
    date_str = d.strftime('%Y%m%d')
    if isinstance(numero_control, str):
        m = re.match(r"^(DTE-\d{2}-[^-]+-)(\d+)$", numero_control)
        if m:
            numero_control = f"{m.group(1)}{int(m.group(2)):015d}"
    base_name = f"{date_str}_{sanitize_filename(empresa)}_{numero_control}_{sanitize_filename(doc_type)}"
    pdf_path = folder / (base_name + '.pdf')
    json_path = folder / (base_name + '.json')
    return pdf_path, json_path


def build_invoice_json(venta, cliente, detalles, template_path=TEMPLATE_PATH):
    """Create an invoice JSON following the template structure."""
    template = Path(template_path)
    try:
        with template.open('r', encoding='utf-8') as fh:
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
            ident['fecEmi'] = datetime.fromisoformat(venta['fecha']).strftime('%Y-%m-%d')
        except ValueError:
            ident['fecEmi'] = str(venta['fecha'])[:10]
    ident.setdefault('version', 1)
    ident.setdefault('ambiente', venta.get('ambiente', '00'))
    ident.setdefault('tipoMoneda', 'USD')
    if venta.get('tipo_operacion') is not None:
        ident['tipoOperacion'] = venta['tipo_operacion']
        ident['tipoModelo'] = 2 if venta['tipo_operacion'] == 2 else 1
    if venta.get('tipo_contingencia') is not None:
        ident['tipoContingencia'] = venta['tipo_contingencia']
    if venta.get('motivo_contin') is not None:
        ident['motivoContin'] = venta['motivo_contin']
    data['identificacion'] = ident

    rec = data.get('receptor', {})
    if cliente:
        if cliente.get('nombre'):
            rec['nombre'] = cliente['nombre']
        if cliente.get('nit'):
            rec['nit'] = cliente['nit']
        if cliente.get('nrc'):
            rec['nrc'] = cliente['nrc']
        if cliente.get('telefono'):
            rec['telefono'] = cliente['telefono']
        correo = cliente.get('correo') or cliente.get('email')
        if correo:
            rec['correo'] = correo
        if cliente.get('nombre_comercial'):
            rec['nombreComercial'] = cliente['nombre_comercial']
        if cliente.get('nombreComercial'):
            rec['nombreComercial'] = cliente['nombreComercial']
        if cliente.get('codActividad'):
            rec['codActividad'] = cliente['codActividad']
        if cliente.get('giro'):
            rec['descActividad'] = cliente['giro']
        direccion = cliente.get('direccion')
        if direccion or cliente.get('departamento') or cliente.get('municipio'):
            if isinstance(direccion, dict):
                dir_src = direccion.copy()
            else:
                dir_src = {'complemento': direccion} if direccion else {}
            if cliente.get('departamento') is not None and 'departamento' not in dir_src:
                dir_src['departamento'] = cliente.get('departamento')
            if cliente.get('municipio') is not None and 'municipio' not in dir_src:
                dir_src['municipio'] = cliente.get('municipio')
            rec['direccion'] = _build_receptor_direccion(dir_src)
    data['receptor'] = rec

    cuerpo = []
    for idx, det in enumerate(detalles or [], 1):
        cuerpo.append({
            'numItem': idx,
            'descripcion': det.get('descripcion'),
            'cantidad': det.get('cantidad'),
            'precioUni': det.get('precio_unitario'),
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

    return data


def list_documents(root=None):
    """Return a list of paired PDF/JSON documents found in folders."""
    base = Path(root) if root else Path(BASE_DIR)
    result: list[dict[str, str]] = []
    for doc_type, folder in FOLDERS.items():
        current = Path(folder)
        if root:
            current = base / current.name
        if not current.is_dir():
            continue
        pairs: dict[str, dict[str, str]] = {}
        for path in current.iterdir():
            if not path.is_file():
                continue
            stem = path.stem
            suffix = path.suffix.lower()
            if suffix == '.pdf':
                pairs.setdefault(stem, {})['pdf'] = str(path)
            elif suffix == '.json':
                pairs.setdefault(stem, {})['json'] = str(path)
        for paths in pairs.values():
            if 'pdf' in paths and 'json' in paths:
                result.append({'tipo': doc_type, 'pdf': paths['pdf'], 'json': paths['json']})
    return result
