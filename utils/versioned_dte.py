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


def _version_dir(base: str, codigo: str, json_hash: str, timestamp: str) -> str:
    return os.path.join(base, codigo, f"{timestamp}-{json_hash}")


def ensure_version(dte_json: dict, base_dir: str | None = None) -> tuple[str, str]:
    """Ensure a directory for the given ``dte_json`` version exists.

    Returns a tuple ``(version_dir, hashJson)``.
    """
    ident = dte_json.get("identificacion", {})
    codigo = ident.get("codigoGeneracion") or "SIN-CODIGO"
    json_hash = hash_json(dte_json)
    base_dir = os.path.abspath(base_dir or os.path.join(os.path.dirname(__file__), "..", "dtes"))
    codigo_dir = os.path.join(base_dir, codigo)
    os.makedirs(codigo_dir, exist_ok=True)
    for name in os.listdir(codigo_dir):
        if name.endswith(f"-{json_hash}"):
            return os.path.join(codigo_dir, name), json_hash
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    version_dir = _version_dir(base_dir, codigo, json_hash, timestamp)
    os.makedirs(version_dir, exist_ok=True)
    save_file(os.path.join(version_dir, "documento.json"), stable_stringify(dte_json, indent=2))
    meta = {
        "codigoGeneracion": codigo,
        "hashJson": json_hash,
        "timestamp": timestamp,
        "estado": "borrador",
        "firmas": [],
    }
    save_file(os.path.join(version_dir, "metadata.json"), stable_stringify(meta, indent=2))
    return version_dir, json_hash


def add_jws(version_dir: str, token: str, origen: str = "manual", estado: str = "borrador") -> str:
    """Store ``token`` under ``version_dir`` registering metadata."""
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    jws_filename = f"documento-{ts}.jws"
    save_file(os.path.join(version_dir, jws_filename), token, add_final_newline=False)
    meta_path = os.path.join(version_dir, "metadata.json")
    try:
        with open(meta_path, "r", encoding="utf-8") as fh:
            meta = json.load(fh)
    except Exception:
        meta = {"firmas": []}
    meta.setdefault("firmas", []).append(
        {
            "archivo": jws_filename,
            "fechaFirma": ts,
            "origen": origen,
            "estado": estado,
        }
    )
    save_file(meta_path, stable_stringify(meta, indent=2))
    return jws_filename


def promote(version_dir: str, jws_filename: str) -> None:
    """Mark the pair as ready for sending."""
    meta_path = os.path.join(version_dir, "metadata.json")
    with open(meta_path, "r", encoding="utf-8") as fh:
        meta = json.load(fh)
    meta["estado"] = "lista"
    for firma in meta.get("firmas", []):
        if firma.get("archivo") == jws_filename:
            firma["estado"] = "lista"
    save_file(meta_path, stable_stringify(meta, indent=2))


def verify(version_dir: str, jws_filename: str) -> None:
    """Validate that ``jws_filename`` matches the stored JSON version."""
    json_path = os.path.join(version_dir, "documento.json")
    with open(json_path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    meta_path = os.path.join(version_dir, "metadata.json")
    try:
        with open(meta_path, "r", encoding="utf-8") as fh:
            meta = json.load(fh)
    except Exception:
        meta = {}
    if meta.get("hashJson") != hash_json(data):
        raise ValueError(
            "La firma no corresponde a la versión actual del documento. Vuelva a firmar o seleccione una firma compatible."
        )
    jws_path = os.path.join(version_dir, jws_filename)
    with open(jws_path, "r", encoding="utf-8") as fh:
        token = fh.read()
    payload = decode_jws_payload(token)
    ident_payload = payload.get("identificacion") or payload.get("identificador") or payload
    ident_json = data.get("identificacion") or data.get("identificador") or data
    for key in ("codigoGeneracion", "tipoDte", "version"):
        if str(ident_payload.get(key)) != str(ident_json.get(key)):
            raise ValueError(
                "La firma no corresponde a la versión actual del documento. Vuelva a firmar o seleccione una firma compatible."
            )


__all__ = [
    "ensure_version",
    "add_jws",
    "promote",
    "verify",
    "decode_jws_payload",
    "hash_json",
]
