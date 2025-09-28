from __future__ import annotations

import base64
import json
import os
from datetime import datetime

from .stable_json import stable_stringify, save_file, hash_json
from paths import DTES_DIR


def decode_jws_payload(token: str) -> dict:
    """Return the payload of a compact JWS token."""
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("JWS malformado")
    payload = parts[1]
    padding = "=" * (-len(payload) % 4)
    data = base64.urlsafe_b64decode(payload + padding)
    return json.loads(data.decode("utf-8"))


def resolve_version_dir(base_dir: str | None, codigo: str) -> str:
    """Return the directory that stores ``codigo`` within ``base_dir``."""

    base = os.path.abspath(base_dir or DTES_DIR)
    codigo = (codigo or "").strip()
    if not codigo:
        raise ValueError("codigo_generacion inválido para snapshot")
    return os.path.join(base, codigo)


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
    version_dir = resolve_version_dir(base_dir, codigo)
    os.makedirs(version_dir, exist_ok=True)
    save_file(
        os.path.join(version_dir, "documento.json"),
        stable_stringify(dte_json, indent=2),
    )
    return version_dir, json_hash


def save_estado(version_dir: str, data: dict) -> str:
    """Store ``data`` representing the final state of the DTE."""

    # Ensure the state file shares the same base name as the original JSON
    # stored in ``version_dir``.  When the directory only contains
    # ``documento.json`` this will default to ``documento``; otherwise the
    # existing JSON filename (sans extension) is reused.
    base_name = None
    try:
        for fname in os.listdir(version_dir):
            if not fname.endswith(".json"):
                continue
            stem = os.path.splitext(fname)[0]
            if stem.endswith("_estado") or stem.endswith("_aceptado") or stem.endswith("_rechazado"):
                continue
            base_name = stem
            break
    except OSError:  # pragma: no cover - best effort
        base_name = None
    if not base_name:
        base_name = "documento"

    estado = str(data.get("estado", "")).lower()
    if estado == "aceptado":
        suffix = "aceptado"
    elif estado == "rechazado":
        suffix = "rechazado"
    else:
        suffix = "estado"
    name = f"{base_name}_{suffix}.json"
    save_file(os.path.join(version_dir, name), stable_stringify(data, indent=2))
    return name


__all__ = [
    "ensure_version",
    "save_estado",
    "decode_jws_payload",
    "hash_json",
    "resolve_version_dir",
]
