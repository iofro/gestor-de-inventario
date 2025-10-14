import os

import pytest

from utils import versioned_dte


def _sample_dte():
    return {
        "identificacion": {
            "codigoGeneracion": "00000000-0000-4000-8000-000000000001",
            "tipoDte": "01",
            "version": 1,
        }
    }


def test_store_and_save_estado(tmp_path):
    data = _sample_dte()
    version_dir, json_hash = versioned_dte.ensure_version(data, base_dir=tmp_path)
    assert os.path.exists(os.path.join(version_dir, "documento.json"))
    assert json_hash
    state = {"estado": "Aceptado"}
    name = versioned_dte.save_estado(version_dir, state)
    assert name == "documento_aceptado.json"
    assert os.path.exists(os.path.join(version_dir, name))


def test_ensure_version_rejects_mismatch(tmp_path):
    data = _sample_dte()
    versioned_dte.ensure_version(data, base_dir=tmp_path)
    altered = _sample_dte()
    altered["identificacion"]["version"] = 2
    with pytest.raises(RuntimeError):
        versioned_dte.ensure_version(altered, base_dir=tmp_path)
