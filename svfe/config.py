from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

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
    ):
        raise ValueError("Config de dirección del emisor inválida")

    if len(departamento) != 2 or len(municipio) != 2:
        raise ValueError("Config de dirección del emisor inválida")

    return {
        "departamento": departamento,
        "municipio": municipio,
        "complemento": complemento,
    }


__all__ = ["get_emisor_direccion", "CONFIG_PATH"]
