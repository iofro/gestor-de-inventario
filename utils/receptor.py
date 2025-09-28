from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List


_PLACEHOLDERS_RECEPTOR = {
    "nit": "00000000000000",
    "nrc": "0",
    "nombre": "CLIENTE DESCONOCIDO",
    "codActividad": "00000",
    "descActividad": "PENDIENTE",
    "nombreComercial": None,
    "telefono": "00000000",
    "correo": "demo@example.com",
}

_PLACEHOLDERS_DIRECCION = {
    "departamento": "01",
    "municipio": "01",
    "complemento": "DIRECCION PENDIENTE",
}


def ensure_receptor_completo(receptor: Dict[str, Any] | None, ambiente: str) -> Dict[str, Any]:
    """Return a receptor dictionary that satisfies schema requirements for notas.

    Parameters
    ----------
    receptor:
        Receptor dictionary copied from the source DTE.
    ambiente:
        Ambiente value ("00" pruebas, "01" producción).
    """

    rec = deepcopy(receptor or {})
    missing: List[str] = []

    direccion = rec.get("direccion")
    if not isinstance(direccion, dict):
        direccion = {}
    direccion = deepcopy(direccion)

    for field, placeholder in _PLACEHOLDERS_RECEPTOR.items():
        if _needs_placeholder(rec, field):
            if ambiente == "01":
                missing.append(field)
            else:
                rec[field] = placeholder
        elif field == "correo":
            correo = str(rec.get(field, ""))
            if "@" not in correo:
                if ambiente == "01":
                    missing.append(field)
                else:
                    rec[field] = placeholder
        elif field in {"nit", "nrc", "telefono", "codActividad"}:
            value = rec.get(field)
            if value is not None:
                rec[field] = str(value)

    for field, placeholder in _PLACEHOLDERS_DIRECCION.items():
        if _needs_placeholder(direccion, field):
            if ambiente == "01":
                missing.append(f"direccion.{field}")
            else:
                direccion[field] = placeholder
        else:
            direccion[field] = str(direccion[field])

    rec["direccion"] = direccion

    if missing and ambiente == "01":
        raise ValueError(
            "Faltan campos obligatorios en receptor: " + ", ".join(sorted(missing))
        )

    # Asegura que las claves existan aunque sean None.
    for field in _PLACEHOLDERS_RECEPTOR:
        rec.setdefault(field, _PLACEHOLDERS_RECEPTOR[field])
    for field in _PLACEHOLDERS_DIRECCION:
        rec["direccion"].setdefault(field, _PLACEHOLDERS_DIRECCION[field])

    return rec


def _needs_placeholder(data: Dict[str, Any], field: str) -> bool:
    if field not in data:
        return True
    value = data[field]
    if field == "nombreComercial":
        return False
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    return False
