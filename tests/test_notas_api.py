from fastapi.testclient import TestClient
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
