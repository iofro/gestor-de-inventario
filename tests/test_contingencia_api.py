from fastapi.testclient import TestClient
from api.facturas import app, repo
from models.factura import Factura

client = TestClient(app)

def setup_function(_):
    repo._data.clear()

def test_guardar_en_contingencia_actualiza_estado():
    repo.add(Factura(id=1))
    resp = client.post(
        '/api/facturas/1/contingencia',
        json={'tipoContingencia': 1, 'motivoContin': ''},
    )
    assert resp.status_code == 200
    factura = repo.get(1)
    assert factura.modo_transmision == 'contingencia'
    assert factura.estado_envio == 'Pendiente'
    assert factura.tipo_contingencia == 1
    assert factura.motivo_contin == ''

def test_guardar_en_contingencia_idempotente():
    repo.add(
        Factura(
            id=2,
            modo_transmision='contingencia',
            estado_envio='Pendiente',
            tipo_contingencia=1,
        )
    )
    resp = client.post(
        '/api/facturas/2/contingencia',
        json={'tipoContingencia': 1, 'motivoContin': ''},
    )
    assert resp.status_code == 200
    factura = repo.get(2)
    assert factura.modo_transmision == 'contingencia'
    assert factura.estado_envio == 'Pendiente'
    assert factura.tipo_contingencia == 1

def test_guardar_en_contingencia_rechaza_enviado():
    repo.add(Factura(id=3, estado_envio='Enviado'))
    resp = client.post(
        '/api/facturas/3/contingencia',
        json={'tipoContingencia': 1, 'motivoContin': ''},
    )
    assert resp.status_code == 400
