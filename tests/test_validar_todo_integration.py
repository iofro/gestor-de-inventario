import json
import sys
import pytest
from tools import validar_todo


@pytest.fixture
def run_validacion(monkeypatch):
    def _run(ambiente="pruebas", formato="md"):
        monkeypatch.setattr(
            sys, "argv", ["validar_todo.py", "--ambiente", ambiente, "--formato", formato]
        )
        return validar_todo.main()

    return _run


@pytest.fixture
def datos_negocio_incompleto(tmp_path):
    path = tmp_path / "datos_negocio.json"
    path.write_text("{}", encoding="utf-8")
    return path


@pytest.fixture
def datos_negocio_completo(tmp_path):
    data = {
        "nit": "0614-000000-102-2",
        "nrc": "123456-7",
        "razon_social": "Mi Negocio",
        "ciiu": "0000",
        "giro": "Comercio",
        "direccion": "Calle Falsa 123",
        "telefono_movil": "12345678",
        "email": "test@example.com",
    }
    path = tmp_path / "datos_negocio.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_reporta_campos_emisor_faltantes(run_validacion, datos_negocio_incompleto, monkeypatch, capsys):
    monkeypatch.setattr(validar_todo, "DATOS_NEGOCIO_PATH", datos_negocio_incompleto)
    exit_code = run_validacion()
    captured = capsys.readouterr().out
    assert exit_code != 0
    for campo in [
        "nit",
        "nrc",
        "nombre",
        "codActividad",
        "descActividad",
        "direccion.complemento",
        "telefono",
        "correo",
    ]:
        assert f"- {campo}" in captured


def test_reporta_errores_schema(run_validacion, datos_negocio_completo, monkeypatch, capsys):
    monkeypatch.setattr(validar_todo, "DATOS_NEGOCIO_PATH", datos_negocio_completo)
    original_build = validar_todo.build_payload

    def build_payload_con_error(tipo, emisor, ambiente):
        payload = original_build(tipo, emisor, ambiente)
        payload["cuerpoDocumento"].append({"uniMedida": "texto"})
        return payload

    monkeypatch.setattr(validar_todo, "build_payload", build_payload_con_error)
    exit_code = run_validacion(formato="json")
    salida = capsys.readouterr().out
    assert exit_code != 0
    errores = json.loads(salida)
    assert any(e["campo_path"] == "cuerpoDocumento.0.uniMedida" for e in errores)
