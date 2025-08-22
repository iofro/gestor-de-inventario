"""Manual end-to-end test against the Hacienda API.

This script builds a minimal DTE, signs it and sends it to the URL
specified in the ``HACIENDA_URL`` environment variable. The request
payload and Hacienda response are stored under ``.out/`` for manual
inspection.
"""

from __future__ import annotations

import json
import os
import pathlib

import requests

from db import DB
from dte import generar_dte_json
from utils.jws import sign_json


def _build_sample_dte() -> dict:
    """Return a minimal valid DTE using an in-memory database."""
    db = DB(":memory:")
    db.add_vendedor("V1")
    vid = db.cursor.lastrowid
    db.add_producto("Prod", "P1", None,  vid, None, 0, 0, 0, 10)
    pid = db.cursor.lastrowid
    db.add_cliente("Cliente", "123", "0614-987654-321-0", "", "Giro", "", "", "Dir", "", "")
    cid = db.cursor.lastrowid
    venta_id = db.add_venta("2024-01-01", 10, cliente_id=cid)
    db.add_detalle_venta(venta_id, pid, 1, 10, vendedor_id=vid)
    return generar_dte_json(db, venta_id)


def main() -> None:
    url = os.getenv("HACIENDA_URL")
    if not url:
        print("E2E_API_FAIL")
        return

    dte = _build_sample_dte()
    token = sign_json(dte)

    out_dir = pathlib.Path(".out")
    out_dir.mkdir(exist_ok=True)

    with (out_dir / "ultimo_dte.json").open("w", encoding="utf-8") as fh:
        json.dump(dte, fh, ensure_ascii=False, indent=2)

    payload = {"dte": token}
    try:
        resp = requests.post(url, json=payload, timeout=20)
        resp_json = resp.json()
    except Exception as exc:  # pragma: no cover - manual script
        resp = None
        resp_json = {"error": str(exc)}

    with (out_dir / "respuesta_hacienda.json").open("w", encoding="utf-8") as fh:
        json.dump(resp_json, fh, ensure_ascii=False, indent=2)

    estado = str(
        resp_json.get("estado")
        or resp_json.get("estadoDte")
        or resp_json.get("descripcionEstado")
        or resp_json.get("status")
        or ""
    ).upper()

    if resp and resp.status_code == 200 and (
        "RECIB" in estado or "ACEPT" in estado or "PROCES" in estado
    ):
        print("E2E_API_OK")
    else:
        print("E2E_API_FAIL")


if __name__ == "__main__":  # pragma: no cover - manual execution
    main()
