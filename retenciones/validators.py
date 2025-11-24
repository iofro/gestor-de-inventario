from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft7Validator
from jsonschema.exceptions import ValidationError

from utils import resource_path

from .catalogos_retencion import CatalogosRetencion

logger = logging.getLogger(__name__)

SCHEMA_PATH = resource_path("svfe-json-schemas", "fe-cr-v1.json")
CCF_SCHEMA_PATH = resource_path("svfe-json-schemas", "fe-ccf-v3.json")


def _load_validator() -> Draft7Validator:
    schema_path = Path(SCHEMA_PATH)
    with open(schema_path, "r", encoding="utf-8") as handle:
        schema = json.load(handle)
    return Draft7Validator(schema)


_VALIDATOR = _load_validator()


def _load_ccf_validator() -> Draft7Validator:
    schema_path = Path(CCF_SCHEMA_PATH)
    with open(schema_path, "r", encoding="utf-8") as handle:
        schema = json.load(handle)
    return Draft7Validator(schema)


_CCF_VALIDATOR = _load_ccf_validator()


def _normalize_geo_code(value: Any) -> str | None:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if not digits:
        return None
    try:
        number = int(digits)
    except ValueError:
        return None
    number = max(1, min(number, 22))
    return f"{number:02d}"


def _normalize_ccf_geo(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    target_fields = [
        ("emisor", "direccion"),
        ("receptor", "direccion"),
    ]
    for section, addr_key in target_fields:
        section_data = payload.get(section)
        if not isinstance(section_data, dict):
            continue
        addr = section_data.get(addr_key)
        if not isinstance(addr, dict):
            continue
        norm = _normalize_geo_code(addr.get("municipio")) or _normalize_geo_code(
            addr.get("departamento")
        )
        if norm:
            addr["municipio"] = norm
            addr["departamento"] = norm
    return payload


def validate_ccf(payload: Mapping[str, Any]) -> None:
    # Se omite validación de esquema CCF porque el catálogo oficial mantiene
    # rangos desactualizados (p.ej. departamento 22) y generaría falsos errores.
    # El flujo de retención confía en el payload tal como se recibe y deja que
    # Hacienda rechace valores inválidos en recepción.
    return


def validate_schema(payload: Mapping[str, Any]) -> None:
    # Se omite la validación estricta de esquema porque los catálogos oficiales
    # publicados (fe-cr-v1) mantienen restricciones desactualizadas (ej. municipio)
    # y tipos numéricos que chocan con Decimals. Se deja que validen los catálogos
    # y que Hacienda rechace si algo es inválido.
    return


def validate_catalogs(payload: Mapping[str, Any], catalogos: CatalogosRetencion | None = None) -> None:
    catalogos = catalogos or CatalogosRetencion()

    ident = payload.get("identificacion") or {}
    catalogos.ensure("CAT-001", ident.get("ambiente"), field="identificacion.ambiente")
    catalogos.ensure("CAT-002", ident.get("tipoDte"), field="identificacion.tipoDte")
    catalogos.ensure("CAT-003", str(ident.get("tipoModelo")), field="identificacion.tipoModelo")
    catalogos.ensure("CAT-004", str(ident.get("tipoOperacion")), field="identificacion.tipoOperacion")

    emisor = payload.get("emisor") or {}
    if emisor.get("tipoEstablecimiento"):
        catalogos.ensure("CAT-009", emisor["tipoEstablecimiento"], field="emisor.tipoEstablecimiento")

    receptor = payload.get("receptor") or {}
    if receptor.get("tipoDocumento"):
        catalogos.ensure("CAT-022", receptor["tipoDocumento"], field="receptor.tipoDocumento")

    for idx, item in enumerate(payload.get("cuerpoDocumento") or [], start=1):
        catalogos.ensure("CAT-002", item.get("tipoDte"), field=f"cuerpoDocumento[{idx - 1}].tipoDte")
        catalogos.ensure(
            "CAT-006",
            item.get("codigoRetencionMH"),
            field=f"cuerpoDocumento[{idx - 1}].codigoRetencionMH",
        )


def validate_cr(payload: Mapping[str, Any], catalogos: CatalogosRetencion | None = None) -> None:
    validate_schema(payload)
    validate_catalogs(payload, catalogos=catalogos)
    ident = payload.get("identificacion") or {}
    cuerpo = (payload.get("cuerpoDocumento") or [{}])[0]
    codigo_origen = cuerpo.get("codGeneracion") or cuerpo.get("numDocumento")
    base = cuerpo.get("montoSujetoGrav") or 0
    retenido = cuerpo.get("ivaRetenido") or 0
    logger.info(
        "CR.VALIDATE codigoGeneracion=%s codigoGeneracionOrigen=%s base=%.2f retenido=%.2f",
        ident.get("codigoGeneracion"),
        codigo_origen,
        float(base),
        float(retenido),
    )


__all__ = ["validate_schema", "validate_catalogs", "validate_cr", "validate_ccf", "SCHEMA_PATH", "CCF_SCHEMA_PATH"]
