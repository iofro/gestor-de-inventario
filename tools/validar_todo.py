import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List

import csv
import io
from jsonschema import Draft7Validator, ValidationError

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parents[1]
DATOS_NEGOCIO_PATH = BASE_DIR / "datos_negocio.json"
SCHEMAS_DIR = BASE_DIR / "svfe-json-schemas"

TIPOS_DTE = [
    "FE",
    "CCFE",
    "NRE",
    "NCE",
    "NDE",
    "FEXE",
    "FSEE",
    "CRE",
    "CLE",
    "DCLE",
    "CDE",
]

CODIGO_TIPO = {
    "FE": "01",
    "CCFE": "03",
    "NRE": "04",
    "NCE": "05",
    "NDE": "06",
    "FEXE": "11",
    "FSEE": "14",
    "CRE": "07",
    "CLE": "08",
    "DCLE": "09",
    "CDE": "15",
}

SCHEMA_MAP = {
    "FE": SCHEMAS_DIR / "fe-fc-v1.json",
    "CCFE": SCHEMAS_DIR / "fe-ccf-v3.json",
    "NRE": SCHEMAS_DIR / "fe-nr-v3.json",
    "NCE": SCHEMAS_DIR / "fe-nc-v3.json",
    "NDE": SCHEMAS_DIR / "fe-nd-v3.json",
    "FEXE": SCHEMAS_DIR / "fe-fex-v1.json",
    "FSEE": SCHEMAS_DIR / "fe-fse-v1.json",
    "CRE": SCHEMAS_DIR / "fe-cr-v1.json",
    "CLE": SCHEMAS_DIR / "fe-cl-v1.json",
    "DCLE": SCHEMAS_DIR / "fe-dcl-v1.json",
    "CDE": SCHEMAS_DIR / "fe-cd-v1.json",
}


def _load_emisor() -> Dict[str, Any]:
    if not DATOS_NEGOCIO_PATH.exists():
        logger.error("No se encontró datos_negocio.json")
        return {}
    try:
        with DATOS_NEGOCIO_PATH.open("r", encoding="utf-8") as fh:
            datos = json.load(fh)
    except Exception as exc:  # pragma: no cover
        logger.error("Error cargando datos_negocio.json: %s", exc)
        return {}

    emisor = {
        "nit": datos.get("nit"),
        "nrc": datos.get("nrc"),
        "nombre": datos.get("razon_social") or datos.get("nombre_comercial"),
        "codActividad": datos.get("ciiu"),
        "descActividad": datos.get("giro"),
        "direccion": {"complemento": datos.get("direccion")},
        "telefono": datos.get("telefono_movil") or datos.get("telefono_fijo"),
        "correo": datos.get("email"),
    }
    return emisor


def _validate_emisor(emisor: Dict[str, Any]) -> List[str]:
    required = [
        "nit",
        "nrc",
        "nombre",
        "codActividad",
        "descActividad",
        ("direccion", "complemento"),
        "telefono",
        "correo",
    ]
    missing: List[str] = []
    for key in required:
        if isinstance(key, tuple):
            val = emisor.get(key[0], {}).get(key[1]) if emisor.get(key[0]) else None
            if val is None or (isinstance(val, str) and not val.strip()):
                missing.append(f"{key[0]}.{key[1]}")
        else:
            val = emisor.get(key)
            if val is None or (isinstance(val, str) and not val.strip()):
                missing.append(key)
    return missing


def build_payload(tipo: str, emisor: Dict[str, Any], ambiente: str) -> Dict[str, Any]:
    codigo = CODIGO_TIPO.get(tipo, "")
    payload = {
        "identificacion": {
            "version": "1",
            "tipoDte": codigo,
            "ambiente": "01" if ambiente == "produccion" else "00",
        },
        "emisor": emisor,
        "receptor": {},
        "cuerpoDocumento": [],
        "resumen": {},
    }
    return payload


def validate_dte_json(instance: Dict[str, Any], *, tipo: str, ambiente: str, strict: bool = True) -> None:
    required = ["identificacion", "emisor", "receptor", "cuerpoDocumento", "resumen"]
    missing = [k for k in required if k not in instance]
    if missing:
        raise ValueError(
            ", ".join(missing)
        )
    schema_path = SCHEMA_MAP.get(tipo)
    if not schema_path or not schema_path.exists():
        raise ValueError(f"Esquema no encontrado para tipo {tipo}")
    with schema_path.open("r", encoding="utf-8") as fh:
        schema = json.load(fh)
    validator = Draft7Validator(schema)
    errors = list(validator.iter_errors(instance))
    if errors:
        raise ValidationError("Errores de esquema")


def generar_reporte(errores: List[Dict[str, Any]], formato: str) -> str:
    if formato == "json":
        return json.dumps(errores, ensure_ascii=False, indent=2)
    if formato == "csv":
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["tipo", "campo", "mensaje"])
        for err in errores:
            writer.writerow([err["tipo"], err["campo_path"], err["mensaje"]])
        return buffer.getvalue()
    # Markdown
    lines: List[str] = []
    for tipo in TIPOS_DTE:
        tipo_errs = [e for e in errores if e["tipo"] == tipo]
        if not tipo_errs:
            continue
        lines.append(f"### {tipo}")
        lines.append("| Tipo | Campo | Error/Detalle |")
        lines.append("| --- | --- | --- |")
        for e in tipo_errs:
            lines.append(f"| {e['tipo']} | {e['campo_path']} | {e['mensaje']} |")
        lines.append("")
    if not lines:
        return "Sin errores"
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Valida todos los tipos de DTE")
    parser.add_argument("--ambiente", choices=["pruebas", "produccion"], required=True)
    parser.add_argument("--salida")
    parser.add_argument(
        "--formato", choices=["md", "csv", "json"], default="md"
    )
    parser.add_argument("--detener_en_fatal", action="store_true")
    args = parser.parse_args()

    emisor = _load_emisor()
    missing = _validate_emisor(emisor)
    if missing:
        mensaje = ", ".join(missing)
        logging.error("Faltan campos obligatorios en emisor: %s", mensaje)
        print("Faltan campos obligatorios en emisor:")
        for m in missing:
            print(f"- {m}")
        return 1

    errores: List[Dict[str, Any]] = []

    for tipo in TIPOS_DTE:
        logger.info("Validando %s", tipo)
        schema_path = SCHEMA_MAP.get(tipo)
        payload = build_payload(tipo, emisor, args.ambiente)
        try:
            validate_dte_json(payload, tipo=tipo, ambiente=args.ambiente, strict=True)
        except ValueError as exc:
            faltantes = [p.strip() for p in str(exc).split(",")]
            for campo in faltantes:
                errores.append(
                    {
                        "tipo": tipo,
                        "severidad": "fatal",
                        "campo_path": campo,
                        "mensaje": "Campo faltante",
                    }
                )
            if args.detener_en_fatal:
                break
        except ValidationError:
            if schema_path and schema_path.exists():
                with schema_path.open("r", encoding="utf-8") as fh:
                    schema = json.load(fh)
                validator = Draft7Validator(schema)
                for err in sorted(validator.iter_errors(payload), key=lambda e: e.path):
                    path = ".".join(str(p) for p in err.path) or "<root>"
                    errores.append(
                        {
                            "tipo": tipo,
                            "severidad": "error",
                            "campo_path": path,
                            "mensaje": err.message,
                        }
                    )
            else:
                errores.append(
                    {
                        "tipo": tipo,
                        "severidad": "fatal",
                        "campo_path": "<schema>",
                        "mensaje": "Esquema no encontrado",
                    }
                )
                if args.detener_en_fatal:
                    break

    reporte = generar_reporte(errores, args.formato)
    if args.salida:
        Path(args.salida).write_text(reporte, encoding="utf-8")
    else:
        print(reporte)

    return 1 if errores else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
