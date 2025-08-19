from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

DEPARTAMENTO_CODES = {f"{i:02d}" for i in range(1, 15)}
MUNICIPIO_RANGES = {
    "05": ("01", "22"),
    "06": ("01", "19"),
}


def _map_departamento(nombre: str | None) -> str:
    if nombre is None:
        raise ValueError("Departamento requerido")
    nombre = str(nombre)
    if nombre.isdigit():
        nombre = nombre.zfill(2)
    if nombre not in DEPARTAMENTO_CODES:
        raise ValueError("Departamento inválido")
    return nombre


def _map_municipio(nombre: str | None, departamento: str | None = None) -> str:
    if nombre is None:
        raise ValueError("Municipio requerido")
    nombre = str(nombre)
    if not nombre.isdigit() or len(nombre) != 2:
        raise ValueError("Municipio inválido")
    if departamento:
        dep_code = _map_departamento(departamento)
        start, end = MUNICIPIO_RANGES.get(dep_code, ("00", "99"))
        if nombre < start or nombre > end:
            raise ValueError("Municipio inválido para el departamento")
    return nombre

# Path to company configuration holding the emitter address codes
CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "company.json"


def get_emisor_direccion() -> Dict[str, str]:
    """Return the emitter address configuration.

    The configuration must provide ``departamento`` and ``municipio`` as
    two-digit strings plus a ``complemento``. If the file is missing or the
    values do not meet these requirements, ``ValueError`` is raised.
    """

    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - defensive
        raise ValueError("Config de dirección del emisor inválida") from exc

    emisor = data.get("emisor", {})
    departamento = emisor.get("departamento")
    municipio = emisor.get("municipio")
    complemento = emisor.get("complemento")

    if (
        not isinstance(departamento, str)
        or not isinstance(municipio, str)
        or not isinstance(complemento, str)
        or len(departamento) != 2
        or len(municipio) != 2
    ):
        raise ValueError("Config de dirección del emisor inválida")

    try:
        departamento = _map_departamento(departamento)
        municipio = _map_municipio(municipio, departamento)
    except Exception as exc:  # pragma: no cover - invalid codes
        raise ValueError("Config de dirección del emisor inválida") from exc

    return {
        "departamento": departamento,
        "municipio": municipio,
        "complemento": complemento,
    }


__all__ = ["get_emisor_direccion", "CONFIG_PATH", "MUNICIPIO_RANGES"]
