import json
import os
import jwt
import pytest

from utils import versioned_dte
from utils.stable_json import stable_stringify


def _sample_dte():
    return {
        "identificacion": {
            "codigoGeneracion": "00000000-0000-4000-8000-000000000001",
            "tipoDte": "01",
            "version": 1,
        }
    }


def test_store_and_promote(tmp_path):
    data = _sample_dte()
    version_dir, json_hash = versioned_dte.ensure_version(data, base_dir=tmp_path)
    token = jwt.encode(data, "secret", algorithm="HS256")
    jws_name = versioned_dte.add_jws(version_dir, token, origen="manual")

    meta_path = os.path.join(version_dir, "metadata.json")
    meta = json.load(open(meta_path))
    assert meta["hashJson"] == json_hash
    assert meta["firmas"][0]["archivo"] == jws_name
    assert meta["firmas"][0]["estado"] == "borrador"

    versioned_dte.promote(version_dir, jws_name)
    meta = json.load(open(meta_path))
    assert meta["estado"] == "lista"
    assert meta["firmas"][0]["estado"] == "lista"


def test_verify_detects_mismatch(tmp_path):
    data = _sample_dte()
    version_dir, _ = versioned_dte.ensure_version(data, base_dir=tmp_path)
    good_token = jwt.encode(data, "secret", algorithm="HS256")
    good_name = versioned_dte.add_jws(version_dir, good_token)

    # Verification passes for matching token
    versioned_dte.verify(version_dir, good_name)

    bad_payload = _sample_dte()
    bad_payload["identificacion"]["codigoGeneracion"] = "11111111-1111-4111-8111-111111111111"
    bad_token = jwt.encode(bad_payload, "secret", algorithm="HS256")
    bad_name = versioned_dte.add_jws(version_dir, bad_token)

    with pytest.raises(ValueError):
        versioned_dte.verify(version_dir, bad_name)

    # Tamper with JSON after signing
    json_path = os.path.join(version_dir, "documento.json")
    obj = json.load(open(json_path))
    obj["nuevo"] = "cambio"
    from utils.stable_json import save_file

    save_file(json_path, stable_stringify(obj, indent=2))
    with pytest.raises(ValueError):
        versioned_dte.verify(version_dir, good_name)
