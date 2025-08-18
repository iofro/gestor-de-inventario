import json
from pathlib import Path

import pytest
from svfe.generators import (
    generar_consumidor_final as generar_fc_ejemplo,
    strip_extras,
    validar_contra_schema as validate_against_schema,
)

SCHEMA_FC = Path(__file__).resolve().parent.parent / "svfe-json-schemas" / "fe-fc-v1.json"


def test_fc_min_valido():
    dte = generar_fc_ejemplo()
    payload = strip_extras(dte)
    validate_against_schema(payload, "fc")
    item = payload["cuerpoDocumento"][0]
    assert str(item["ventaGravada"]) == "23.85000000"
    assert str(item["ivaItem"]) == "3.10050000"
    assert str(payload["resumen"]["totalGravada"]) == "23.85"
    assert str(payload["resumen"]["totalIva"]) == "3.10"
    assert str(payload["resumen"]["totalPagar"]) == "26.95"


def test_fc_cod_tributo_invalido(tmp_path, monkeypatch):
    dte = generar_fc_ejemplo()
    # Crear una copia del esquema excluyendo el código "19".
    with open(SCHEMA_FC, "r", encoding="utf-8") as fh:
        schema = json.load(fh)
    enum = schema["properties"]["cuerpoDocumento"]["items"]["properties"]["codTributo"]["enum"]
    if "19" in enum:
        enum.remove("19")
    patched_path = tmp_path / "fe-fc-v1.json"
    with open(patched_path, "w", encoding="utf-8") as fh:
        json.dump(schema, fh)
    # Redirigir el validador para que use el esquema modificado.
    import svfe.generators as gen_mod

    monkeypatch.setattr(gen_mod, "SCHEMAS_DIR", tmp_path)
    monkeypatch.setitem(gen_mod.SCHEMA_MAP, "fc", (patched_path.name, "01"))

    with pytest.raises(ValueError) as e:
        validate_against_schema(strip_extras(dte), "fc")
    msg = str(e.value)
    assert "cuerpoDocumento.0.codTributo" in msg
