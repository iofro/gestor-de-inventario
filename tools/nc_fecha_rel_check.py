"""Validacion rapida de fecha relacionada para Nota de Credito.

Uso:
    python tools/nc_fecha_rel_check.py --nota-id 123
    python tools/nc_fecha_rel_check.py --last
    python tools/nc_fecha_rel_check.py --nota-id 123 --db "C:/ruta/inventario.db"

La validacion compara:
- fecha esperada del documento base (snapshot > envio > venta)
- fecha enviada en documentoRelacionado[0].fechaEmision de la NC generada

Retorna codigo de salida:
- 0: coincide
- 1: no coincide o no se pudo validar
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

# Permite ejecutar el script directamente desde tools/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db import DB  # noqa: E402
from nota_credito_electronica import generar_nce_desde_nota  # noqa: E402
from utils.fecha import fecha_ddmmaaaa, fecha_iso  # noqa: E402


_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _normalize_to_iso(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    # Recorta timestamps ISO (YYYY-MM-DDTHH:MM:SS)
    if "T" in text and len(text) >= 10:
        text = text[:10]
    if _ISO_RE.fullmatch(text):
        return text
    ddmmyyyy = fecha_ddmmaaaa(text)
    if ddmmyyyy:
        try:
            return fecha_iso(ddmmyyyy)
        except Exception:
            return None
    return None


def _resolve_expected_fecha_iso(db: DB, venta_id: int | None) -> tuple[str | None, str]:
    if venta_id is None:
        return None, "sin_venta"

    snapshot = db.get_snapshot_by_venta(venta_id)
    if snapshot and snapshot.fecha_emision:
        snapshot_iso = _normalize_to_iso(snapshot.fecha_emision)
        if snapshot_iso:
            return snapshot_iso, "snapshot"

    fecha_envio = db.get_envio_fecha_emision(venta_id)
    envio_iso = _normalize_to_iso(fecha_envio)
    if envio_iso:
        return envio_iso, "envio"

    venta = db.get_venta_by_id(venta_id)
    if venta:
        venta_iso = _normalize_to_iso(venta.get("fecha"))
        if venta_iso:
            return venta_iso, "venta"

    return None, "desconocido"


def _pick_nota_id(db: DB, nota_id: int | None, use_last: bool) -> int:
    if nota_id is not None:
        return int(nota_id)

    if not use_last:
        raise ValueError("Indica --nota-id o usa --last")

    row = db.cursor.execute(
        "SELECT id FROM notas WHERE tipo='credito' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if not row:
        raise ValueError("No existe ninguna nota de credito en la base de datos")
    return int(row["id"] if hasattr(row, "keys") else row[0])


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Valida fechaEmision de documentoRelacionado en Nota de Credito"
    )
    parser.add_argument("--nota-id", type=int, default=None, help="ID de la nota")
    parser.add_argument(
        "--last",
        action="store_true",
        help="Usa la ultima nota de credito registrada",
    )
    parser.add_argument(
        "--db",
        dest="db_path",
        default=None,
        help="Ruta al inventario.db (opcional)",
    )
    parser.add_argument(
        "--ambiente",
        default="00",
        choices=["00", "01", "pruebas", "produccion"],
        help="Ambiente para regenerar NCE (default: 00)",
    )
    parser.add_argument(
        "--strict-snapshot",
        action="store_true",
        help="Exige snapshot al regenerar la NCE",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Imprime tambien un bloque JSON con detalle",
    )

    args = parser.parse_args()

    db = DB(args.db_path)

    try:
        nota_id = _pick_nota_id(db, args.nota_id, args.last)
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1

    nota_row = db.cursor.execute("SELECT * FROM notas WHERE id=?", (nota_id,)).fetchone()
    if not nota_row:
        print(f"ERROR: nota_id={nota_id} no existe")
        return 1
    nota = dict(nota_row)
    venta_id = nota.get("venta_id")

    expected_iso, expected_source = _resolve_expected_fecha_iso(db, venta_id)

    try:
        payload = generar_nce_desde_nota(
            db,
            nota_id,
            ambiente=args.ambiente,
            strict_snapshot=args.strict_snapshot,
        )
    except Exception as exc:
        print(f"ERROR: no se pudo generar NCE para nota_id={nota_id}: {exc}")
        return 1

    ident = payload.get("identificacion") or {}
    rel_list = payload.get("documentoRelacionado") or []
    rel = rel_list[0] if rel_list and isinstance(rel_list[0], dict) else {}

    actual_raw = rel.get("fechaEmision")
    actual_iso = _normalize_to_iso(actual_raw)

    ok = bool(expected_iso and actual_iso and expected_iso == actual_iso)

    print("Validacion NC fecha relacionada")
    print(f"- nota_id: {nota_id}")
    print(f"- venta_id: {venta_id}")
    print(f"- esperado: {expected_iso or 'N/D'} (fuente: {expected_source})")
    print(f"- actual:   {actual_iso or 'N/D'} (raw: {actual_raw!r})")
    print(f"- fecEmi NC: {ident.get('fecEmi')}")

    if args.json:
        detail = {
            "nota_id": nota_id,
            "venta_id": venta_id,
            "esperado": expected_iso,
            "fuente_esperado": expected_source,
            "actual": actual_iso,
            "actual_raw": actual_raw,
            "fecEmi_nc": ident.get("fecEmi"),
            "doc_rel": rel,
        }
        print("\\nDetalle JSON:")
        print(json.dumps(detail, ensure_ascii=False, indent=2))

    if ok:
        print("\\nRESULTADO: OK (la fecha relacionada coincide)")
        return 0

    if not expected_iso:
        print("\\nRESULTADO: NO CONCLUYENTE (sin fecha esperada confiable)")
    else:
        print("\\nRESULTADO: ERROR (la fecha relacionada no coincide)")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
