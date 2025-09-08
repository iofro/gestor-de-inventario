from fastapi.testclient import TestClient
import json
from pathlib import Path
import api.notas as notas_api
from models.factura import Factura

client = TestClient(notas_api.app)


def setup_function(_):
    notas_api.repo._data.clear()
    notas_api.db.cursor.execute("DELETE FROM notas")
    notas_api.db.cursor.execute("DELETE FROM ventas")
    notas_api.db.cursor.execute("DELETE FROM clientes")
    notas_api.db.conn.commit()


def test_crear_nota_credito_transmite(monkeypatch):
    called = {}

    def fake_envio(db, nota_id):
        called["id"] = nota_id
        return {"ok": True}

    monkeypatch.setattr(notas_api, "enviar_nota_credito", fake_envio)
    notas_api.db.add_cliente("Juan", "", "", "", "", "", "", "", "", "")
    cliente_id = notas_api.db.cursor.lastrowid
    venta_id = notas_api.db.add_venta("2024-01-01", 100, cliente_id=cliente_id)
    resp = client.post(
        "/api/notas",
        json={"tipo": "credito", "venta_id": venta_id, "fecha": "2024-01-02", "monto": 10, "motivo": "Dev"},
    )
    assert resp.status_code == 200
    assert called["id"] == 1


def test_get_factura():
    notas_api.repo.add(Factura(id=5))
    resp = client.get("/api/facturas/5")
    assert resp.status_code == 200
    assert resp.json()["factura"]["id"] == 5


def test_credito_no_excede_saldo_api(monkeypatch):
    monkeypatch.setattr(notas_api, "enviar_nota_credito", lambda *a, **k: {"ok": True})
    notas_api.db.add_cliente("Ana", "", "", "", "", "", "", "", "", "")
    cliente_id = notas_api.db.cursor.lastrowid
    venta_id = notas_api.db.add_venta("2024-01-01", 50, cliente_id=cliente_id)
    resp = client.post(
        "/api/notas",
        json={"tipo": "credito", "venta_id": venta_id, "fecha": "2024-01-02", "monto": 60, "motivo": "Dev"},
    )
    assert resp.status_code == 400


def _cargar_fixtures():
    fixtures = Path(__file__).parent / "fixtures"
    factura = json.loads((fixtures / "factura_ejemplo.json").read_text())
    notas_previas = json.loads((fixtures / "notas_previas.json").read_text())
    return factura, notas_previas


def test_credito_respetar_limite_con_notas_previas(monkeypatch):
    monkeypatch.setattr(notas_api, "enviar_nota_credito", lambda *a, **k: {"ok": True})
    factura, notas_previas = _cargar_fixtures()
    notas_api.db.add_cliente(factura["cliente"]["nombre"], "", "", "", "", "", "", "", "", "")
    cliente_id = notas_api.db.cursor.lastrowid
    venta_id = notas_api.db.add_venta(factura["fecha"], factura["total"], cliente_id=cliente_id)
    for nota in notas_previas:
        notas_api.db.agregar_nota(nota["tipo"], venta_id, nota["fecha"], nota["monto"], nota["motivo"])
    resp = client.post(
        "/api/notas",
        json={
            "tipo": "credito",
            "venta_id": venta_id,
            "fecha": "2024-01-04",
            "monto": 40,
            "motivo": "Dev3",
        },
    )
    assert resp.status_code == 400


def test_credito_acepta_monto_restante(monkeypatch):
    monkeypatch.setattr(notas_api, "enviar_nota_credito", lambda *a, **k: {"ok": True})
    factura, notas_previas = _cargar_fixtures()
    notas_api.db.add_cliente(factura["cliente"]["nombre"], "", "", "", "", "", "", "", "", "")
    cliente_id = notas_api.db.cursor.lastrowid
    venta_id = notas_api.db.add_venta(factura["fecha"], factura["total"], cliente_id=cliente_id)
    for nota in notas_previas:
        notas_api.db.agregar_nota(nota["tipo"], venta_id, nota["fecha"], nota["monto"], nota["motivo"])
    resp = client.post(
        "/api/notas",
        json={
            "tipo": "credito",
            "venta_id": venta_id,
            "fecha": "2024-01-04",
            "monto": 30,
            "motivo": "Dev3",
        },
    )
    assert resp.status_code == 200
