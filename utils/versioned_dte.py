from __future__ import annotations

import base64
import json
import os
from datetime import datetime

from .stable_json import stable_stringify, save_file, hash_json


def decode_jws_payload(token: str) -> dict:
    """Return the payload of a compact JWS token."""
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("JWS malformado")
    payload = parts[1]
    padding = "=" * (-len(payload) % 4)
    data = base64.urlsafe_b64decode(payload + padding)
    return json.loads(data.decode("utf-8"))


def ensure_version(dte_json: dict, base_dir: str | None = None) -> tuple[str, str]:
    """Ensure a directory for the given ``dte_json`` exists.

    Previously this module created versioned subdirectories with metadata and
    stored JWS signatures.  To reduce the number of generated files we now
    keep a single directory per ``codigoGeneracion`` containing only the
    original JSON and, eventually, the final state.
    """
    ident = dte_json.get("identificacion", {})
    codigo = ident.get("codigoGeneracion") or "SIN-CODIGO"
    json_hash = hash_json(dte_json)
    base_dir = os.path.abspath(
        base_dir or os.path.join(os.path.dirname(__file__), "..", "dtes")
    )
    version_dir = os.path.join(base_dir, codigo)
    os.makedirs(version_dir, exist_ok=True)
    save_file(
        os.path.join(version_dir, "documento.json"),
        stable_stringify(dte_json, indent=2),
    )
    return version_dir, json_hash


def save_estado(version_dir: str, data: dict) -> str:
    """Store ``data`` representing the final state of the DTE.

    The file name is chosen based on ``data['estado']`` when available
    (``aceptado.json`` or ``rechazado.json``); otherwise ``estado.json`` is
    used.  The chosen file name is returned.
    """
    estado = str(data.get("estado", "")).lower()
    if estado == "aceptado":
        name = "aceptado.json"
    elif estado == "rechazado":
        name = "rechazado.json"
    else:
        name = "estado.json"
    save_file(os.path.join(version_dir, name), stable_stringify(data, indent=2))
    return name


__all__ = [
    "ensure_version",
    "save_estado",
    "decode_jws_payload",
    "hash_json",
]
