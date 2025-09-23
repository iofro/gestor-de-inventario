from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

from utils.catalogos import CAT_MUNI44 as _CAT_MUNI44_COMPAT

from paths import DATOS_NEGOCIO_PATH as _DATOS_NEGOCIO_PATH

# CAT-012 Departamento (strings de 2 dígitos)
CAT012_DEPARTAMENTOS = {
    "00","01","02","03","04","05","06","07","08","09","10","11","12","13","14"
}

# CAT-013 Municipio (tal como lo entrega Hacienda; mantener códigos numéricos tal cual)
CAT013_MUNICIPIOS = {
    "00","10","11","13","14","15","16","17","18","19","20","21","22","23","24","25","26","27","28","34","35","36"
}

CAT013_MUNICIPIOS_COMPAT: Dict[str, Dict[str, str]] = {
    code: mapping.copy() for code, mapping in _CAT_MUNI44_COMPAT.items()
}

# Exposed path for monkeypatching in tests
DATOS_NEGOCIO_PATH = _DATOS_NEGOCIO_PATH


def load_datos_negocio() -> dict:
    """
    Lee paths.DATOS_NEGOCIO_PATH (UTF-8) y retorna el JSON completo.
    Exige data["direccion"] con:
      - "departamento": str de 2 dígitos en CAT-012 (incluye "00")
      - "municipio":   str en CAT-013 (incluye "00"); conservar tal cual (2 o 3 dígitos según catálogo)
      - "complemento": str no vacío
    Normaliza:
      - departamento: str -> zfill(2)
      - municipio: str -> si es numérico, sin perder dígitos (NO castear a int; NO quitar ceros válidos)
    Valida contra los catálogos provistos abajo.
    Si falta algo o es inválido, lanzar ValueError con mensaje claro.
    """

    path = Path(DATOS_NEGOCIO_PATH)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError("datos_negocio.json inválido") from exc

    direccion = data.get("direccion")
    if not isinstance(direccion, dict):
        raise ValueError("Falta dirección del negocio")

    departamento = str(direccion.get("departamento"))
    municipio = str(direccion.get("municipio"))
    complemento = direccion.get("complemento")

    departamento = departamento.zfill(2)
    if departamento not in CAT012_DEPARTAMENTOS:
        raise ValueError("Departamento inválido")

    if municipio not in CAT013_MUNICIPIOS:
        raise ValueError("Municipio inválido")

    if not isinstance(complemento, str) or not complemento:
        raise ValueError("Complemento inválido")

    data["direccion"] = {
        "departamento": departamento,
        "municipio": municipio,
        "complemento": complemento,
    }
    return data


def get_emisor_direccion() -> Dict[str, str]:
    """
    Wrapper de compatibilidad:
    return load_datos_negocio()["direccion"]
    """

    return load_datos_negocio()["direccion"]


__all__ = [
    "load_datos_negocio",
    "get_emisor_direccion",
    "CAT012_DEPARTAMENTOS",
    "CAT013_MUNICIPIOS",
    "CAT013_MUNICIPIOS_COMPAT",
    "DATOS_NEGOCIO_PATH",
]
