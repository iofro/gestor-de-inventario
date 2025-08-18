import json
import dte


def test_cod_giro_used_for_emisor(tmp_path, monkeypatch):
    datos_path = tmp_path / "datos_negocio.json"
    config_path = tmp_path / "config_negocio.json"
    config_path.write_text(json.dumps({"cod_giro": "99999"}))
    datos_path.write_text("{}")
    monkeypatch.setattr(dte, "DATOS_NEGOCIO_PATH", datos_path)
    monkeypatch.setattr(dte, "CONFIG_NEGOCIO_PATH", config_path)
    payload = {
        "identificacion": {},
        "emisor": {},
        "receptor": {"nombre": "X"},
        "cuerpoDocumento": [],
        "resumen": {},
    }
    try:
        dte.validate_dte_json(payload)
    except Exception:
        pass
    assert payload["emisor"]["codActividad"] == "99999"
