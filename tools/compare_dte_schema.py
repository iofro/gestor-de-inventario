#!/usr/bin/env python3
"""Compare a DTE against its JSON schema and generate a patch.

The script validates the provided DTE JSON against the official schema
and reports the similarity percentage.  If discrepancies are found it
outputs a JSON Patch describing the changes required to conform to the
schema.  When the patched document validates without errors the patch is
stored under ``schema_patches/<tipoDte>.json`` so it can be applied
automatically during future DTE generation.
"""

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

import jsonpatch
from jsonschema import ValidationError

import dte

BASE_DIR = Path(__file__).resolve().parents[1]
SCHEMAS_DIR = BASE_DIR / "svfe-json-schemas"
PATCHES_DIR = BASE_DIR / "schema_patches"

SCHEMA_BY_TIPO = {
    "01": SCHEMAS_DIR / "fe-fc-v1.json",
    "03": SCHEMAS_DIR / "fe-ccf-v3.json",
    "04": SCHEMAS_DIR / "fe-nr-v3.json",
    "05": SCHEMAS_DIR / "fe-nc-v3.json",
    "06": SCHEMAS_DIR / "fe-nd-v3.json",
    "07": SCHEMAS_DIR / "fe-cr-v1.json",
    "08": SCHEMAS_DIR / "fe-cl-v1.json",
    "09": SCHEMAS_DIR / "fe-dcl-v1.json",
    "11": SCHEMAS_DIR / "fe-fex-v1.json",
    "14": SCHEMAS_DIR / "fe-fse-v1.json",
    "15": SCHEMAS_DIR / "fe-cd-v1.json",
}


def _flatten(obj: Any, prefix: List[str] | None = None, result: List[str] | None = None) -> List[str]:
    """Return a list of dotted paths for all leaves in ``obj``."""
    prefix = prefix or []
    result = result or []
    if isinstance(obj, dict):
        for k, v in obj.items():
            _flatten(v, prefix + [str(k)], result)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _flatten(v, prefix + [str(i)], result)
    else:
        result.append(".".join(prefix))
    return result


def _build_patch(errors: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    patch: List[Dict[str, Any]] = []
    for err in errors:
        path = list(err["path"])
        if err["validator"] == "required":
            # message: "'foo' is a required property"
            missing = err["message"].split("'")[1]
            patch.append({"op": "add", "path": "/" + "/".join(path + [missing]), "value": None})
        elif err["validator"] == "additionalProperties":
            extra = err["message"].split("'")[1]
            patch.append({"op": "remove", "path": "/" + "/".join(path + [extra])})
        else:
            patch.append({"op": "replace", "path": "/" + "/".join(path), "value": None})
    return patch


def compare(dte_path: Path) -> None:
    with dte_path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    tipo = str(data.get("identificacion", {}).get("tipoDte"))
    if tipo not in SCHEMA_BY_TIPO:
        raise SystemExit(f"No schema mapping for tipoDte {tipo}")
    schema_file = SCHEMA_BY_TIPO[tipo]
    with schema_file.open("r", encoding="utf-8") as fh:
        schema = json.load(fh)

    try:
        dte._validate_schema(data, schema)
        total_fields = len(_flatten(data))
        similarity = 1.0
        errors: List[Dict[str, Any]] = []
    except ValidationError as exc:
        errors = exc.errors  # type: ignore[attr-defined]
        flat = _flatten(data)
        missing = sum(1 for e in errors if e["validator"] == "required")
        total_fields = len(flat) + missing
        similarity = (total_fields - len(errors)) / total_fields if total_fields else 0

    print(f"Similarity: {similarity * 100:.2f}%")
    if not errors:
        print("DTE conforms to schema.")
        return

    patch = _build_patch(errors)
    print("Suggested patch:")
    print(json.dumps(patch, indent=2))

    patched = jsonpatch.JsonPatch(patch).apply(data, in_place=False)
    try:
        dte._validate_schema(patched, schema)
    except ValidationError as exc:  # pragma: no cover - avoid recursion
        print("Patched DTE still invalid. Not storing patch.")
        for err in exc.errors:
            print(f"- {err['path']}: {err['message']}")
        return

    # Save patch for future generations
    PATCHES_DIR.mkdir(exist_ok=True)
    patch_file = PATCHES_DIR / f"{tipo}.json"
    with patch_file.open("w", encoding="utf-8") as fh:
        json.dump(patch, fh, ensure_ascii=False, indent=2)
    print(f"Patch stored in {patch_file}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compare DTE with schema")
    parser.add_argument("dte_path", type=Path, help="Path to DTE JSON file")
    args = parser.parse_args()
    compare(args.dte_path)
