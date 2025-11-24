#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

from db import DB
from dte import generar_dte_json, resolve_ambiente
from paths import RETENCIONES_DIR
from retenciones.builder import build_cr_payload, serialize_cr, sign_cr
from retenciones.catalogos_retencion import CatalogosRetencion
from retenciones.service import RetencionCRService
from retenciones.validators import validate_cr
from utils.stable_json import save_file


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Genera Comprobantes de Retención (CR).")
    parser.add_argument(
        "--from",
        dest="source",
        help="Ruta al DTE JSON origen (solo DTE 03). Si se omite, utiliza --venta-id.",
    )
    parser.add_argument("--venta-id", type=int, help="ID de la venta para reconstruir la factura origen.")
    parser.add_argument("--tipo-dte", help="Tipo de DTE al generar desde venta (solo 03).")
    parser.add_argument("--rate", default="0.01", help="Tasa de retención (por defecto 0.01).")
    parser.add_argument("--codigo-retencion", default="22", help="Código MH de retención (CAT-006).")
    parser.add_argument("--ambiente", help="Ambiente de destino (00 pruebas, 01 producción).")
    parser.add_argument("--output", help="Ruta del archivo JSON de salida.")
    parser.add_argument("--indent", type=int, default=2, help="Indentación al imprimir el JSON.")
    parser.add_argument("--sign", action="store_true", help="Firmar el CR usando el firmador configurado.")
    parser.add_argument("--sign-output", help="Ruta del archivo .jws resultante al usar --sign.")
    parser.add_argument("--emisor-json", help="Archivo JSON para sobreescribir datos del emisor.")
    parser.add_argument("--receptor-json", help="Archivo JSON para sobreescribir datos del receptor.")
    parser.add_argument("--descripcion", help="Descripción personalizada para documentoRelacionado.")
    parser.add_argument("--send", action="store_true", help="Firma y transmite el CR (requiere --venta-id).")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if not args.source and args.venta_id is None:
        parser.error("Debe proporcionar --from o --venta-id.")

    try:
        tasa = Decimal(str(args.rate))
    except Exception as exc:  # pragma: no cover - error de entrada
        parser.error(f"Tasa inválida: {exc}")

    catalogos = CatalogosRetencion()
    db = DB()
    ambiente = resolve_ambiente(args.ambiente)
    if args.send and args.venta_id is None:
        parser.error("--send requiere --venta-id.")
    service = RetencionCRService(db, catalogos=catalogos) if args.venta_id is not None else None

    try:
        factura = _load_factura(args, db=db, ambiente=ambiente)
        emisor_override = _maybe_load_json(args.emisor_json)
        receptor_override = _maybe_load_json(args.receptor_json)

        if service and args.venta_id is not None:
            payload = service.prepare_cr(
                args.venta_id,
                factura=factura,
                tasa=tasa,
                codigo_retencion=args.codigo_retencion,
                ambiente=ambiente,
                emisor_override=emisor_override,
                receptor_override=receptor_override,
                descripcion=args.descripcion,
            )
        else:
            payload = build_cr_payload(
                factura,
                db=db,
                catalogos=catalogos,
                tasa=tasa,
                codigo_retencion=args.codigo_retencion,
                ambiente=ambiente,
                emisor_override=emisor_override,
                receptor_override=receptor_override,
                descripcion=args.descripcion,
            )
            validate_cr(payload, catalogos=catalogos)

        json_str = serialize_cr(payload, indent=args.indent)
        output_path = _resolve_output_path(args.output, payload)
        if output_path:
            save_file(str(output_path), json_str)
            print(f"CR guardado en {output_path}", file=sys.stderr)

        print(json_str)

        if args.sign:
            if service and args.venta_id is not None:
                signed = service.sign_cr(args.venta_id, payload=payload)
            else:
                signed = sign_cr(payload)
            sign_path = args.sign_output
            if sign_path is None and output_path is not None:
                sign_path = str(output_path.with_suffix(".jws"))
            if sign_path:
                save_file(sign_path, signed, add_final_newline=False)
                print(f"JWS guardado en {sign_path}", file=sys.stderr)
            else:
                print(signed)

        if args.send:
            response = service.send_cr(args.venta_id)  # type: ignore[arg-type]
            print(json.dumps(response, ensure_ascii=False, indent=2), file=sys.stderr)
    except Exception as exc:  # pragma: no cover - CLI guard
        print(f"CR ERROR: {exc}", file=sys.stderr)
        sys.exit(1)


def _load_factura(args: argparse.Namespace, *, db: DB, ambiente: str) -> Mapping[str, Any]:
    if args.source:
        with open(args.source, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, Mapping):
            raise ValueError("El archivo --from debe contener un objeto JSON.")
        return data

    venta_id = args.venta_id
    if venta_id is None:
        raise ValueError("venta_id requerido cuando falta --from")
    venta = db.get_venta_by_id(venta_id)
    if not venta:
        raise ValueError(f"Venta {venta_id} no encontrada")
    tipo = _normalize_tipo_dte(args.tipo_dte) or _infer_tipo_dte(venta)
    if tipo != "03":
        raise ValueError(f"Tipo de DTE no soportado para retención: {tipo!r}")
    return generar_dte_json(db, venta_id, tipo_dte=tipo, ambiente=ambiente)


def _infer_tipo_dte(venta: Mapping[str, Any]) -> str:
    candidates = [
        venta.get("tipo_documento"),
        venta.get("tipoDocumento"),
        venta.get("tipo_dte"),
        venta.get("tipoDte"),
    ]
    extra_raw = venta.get("extra")
    if isinstance(extra_raw, str):
        try:
            extra = json.loads(extra_raw)
        except Exception:
            extra = {}
    elif isinstance(extra_raw, Mapping):
        extra = extra_raw
    else:
        extra = {}
    candidates.append(extra.get("tipo_documento"))
    for candidate in candidates:
        tipo = _normalize_tipo_dte(candidate)
        if tipo:
            return tipo
    # fallback: NRC presente → crédito fiscal
    receptor_nrc = extra.get("nrc") or venta.get("nrc")
    if receptor_nrc:
        return "03"
    return "01"


def _normalize_tipo_dte(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        return f"{int(text):02d}"
    lowered = text.lower()
    mapping = {
        "consumidor final": "01",
        "cf": "01",
        "credito fiscal": "03",
        "crédito fiscal": "03",
        "ccf": "03",
        "sujeto excluido": "14",
        "fse": "14",
    }
    for key, code in mapping.items():
        if key in lowered:
            return code
    return None


def _maybe_load_json(path: str | None) -> Mapping[str, Any] | None:
    if not path:
        return None
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, Mapping):
        raise ValueError(f"{path} no contiene un objeto JSON")
    return data


def _resolve_output_path(user_path: str | None, payload: Mapping[str, Any]) -> Path | None:
    if user_path:
        target = Path(user_path)
    else:
        ident = payload.get("identificacion") or {}
        numero = str(ident.get("numeroControl") or "CR").replace("-", "")
        fecha = (ident.get("fecEmi") or "").replace("-", "")
        name = f"CR_{fecha or '0000'}_{numero}.json"
        target = Path(RETENCIONES_DIR) / name
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


if __name__ == "__main__":
    main()
