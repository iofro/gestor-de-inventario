from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api import facturas as facturas_api
from db import DB
from facturas_db.facturas_repo import FacturasRepo
from models.factura import Factura


@pytest.fixture
def client_repo(tmp_path):
    db_path = tmp_path / "inventario.db"
    db = DB(db_path)
    repo = FacturasRepo(db)

    def override_repo() -> FacturasRepo:
        return repo

    facturas_api.app.dependency_overrides[facturas_api.get_repo] = override_repo
    client = TestClient(facturas_api.app)
    repo.clear()
    try:
        yield client, repo, db_path
    finally:
        repo.clear()
        client.close()
        facturas_api.app.dependency_overrides.clear()
        db.conn.close()


def test_guardar_en_contingencia_actualiza_estado(client_repo):
    client, repo, _ = client_repo
    repo.add(Factura(id=1))
    resp = client.post(
        "/api/facturas/1/contingencia",
        json={
            "modeloFacturacion": 2,
            "tipoTransmision": 2,
            "tipoContingencia": 1,
        },
    )
    assert resp.status_code == 200
    factura = repo.get(1)
    assert factura.modo_transmision == "contingencia"
    assert factura.estado_envio == "Pendiente"
    assert factura.tipo_contingencia == 1
    assert factura.motivo_contin is None


def test_guardar_en_contingencia_idempotente(client_repo):
    client, repo, _ = client_repo
    repo.add(
        Factura(
            id=2,
            modo_transmision="contingencia",
            estado_envio="Pendiente",
            tipo_contingencia=1,
        )
    )
    resp = client.post(
        "/api/facturas/2/contingencia",
        json={
            "modeloFacturacion": 2,
            "tipoTransmision": 2,
            "tipoContingencia": 1,
        },
    )
    assert resp.status_code == 200
    factura = repo.get(2)
    assert factura.modo_transmision == "contingencia"
    assert factura.estado_envio == "Pendiente"
    assert factura.tipo_contingencia == 1


def test_guardar_en_contingencia_rechaza_enviado(client_repo):
    client, repo, _ = client_repo
    repo.add(Factura(id=3, estado_envio="Enviado"))
    resp = client.post(
        "/api/facturas/3/contingencia",
        json={
            "modeloFacturacion": 2,
            "tipoTransmision": 2,
            "tipoContingencia": 1,
        },
    )
    assert resp.status_code == 400


def test_repo_persists_contingencia_between_instances(client_repo):
    client, repo, db_path = client_repo
    repo.add(Factura(id=4))
    motivo = "F" * 510
    resp = client.post(
        "/api/facturas/4/contingencia",
        json={
            "modeloFacturacion": 2,
            "tipoTransmision": 2,
            "tipoContingencia": 5,
            "motivoContingencia": motivo,
        },
    )
    assert resp.status_code == 200

    new_repo = FacturasRepo(DB(db_path))
    factura = new_repo.get(4)
    assert factura is not None
    assert factura.modo_transmision == "contingencia"
    assert factura.estado_envio == "Pendiente"
    assert factura.tipo_contingencia == 5
    assert factura.motivo_contin == motivo.strip()[:500]


def test_repo_persists_estado_enviado(client_repo):
    _, repo, db_path = client_repo
    repo.add(Factura(id=5, estado_envio="Enviado"))

    new_repo = FacturasRepo(DB(db_path))
    factura = new_repo.get(5)
    assert factura is not None
    assert factura.estado_envio == "Enviado"
    assert factura.modo_transmision == "normal"


def test_rechaza_motivo_faltante_para_otro(client_repo):
    client, repo, _ = client_repo
    repo.add(Factura(id=6))
    resp = client.post(
        "/api/facturas/6/contingencia",
        json={
            "modeloFacturacion": 2,
            "tipoTransmision": 2,
            "tipoContingencia": 5,
        },
    )
    assert resp.status_code == 422


def test_acepta_campo_legacy_motivo_contin(client_repo):
    client, repo, _ = client_repo
    repo.add(Factura(id=7))
    resp = client.post(
        "/api/facturas/7/contingencia",
        json={
            "modeloFacturacion": 2,
            "tipoTransmision": 2,
            "tipoContingencia": 5,
            "motivoContin": "causa",
        },
    )
    assert resp.status_code == 200
    factura = repo.get(7)
    assert factura.motivo_contin == "causa"
