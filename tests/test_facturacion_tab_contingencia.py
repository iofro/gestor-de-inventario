import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from facturacion_tab import FacturacionTab
except ImportError as exc:  # pragma: no cover - skip when Qt is unavailable
    pytest.skip(f"PyQt5 no disponible: {exc}", allow_module_level=True)

from db import DB


def test_detectar_estado_factura_marca_contingencia(tmp_path):
    db_path = tmp_path / "inventario.db"
    database = DB(db_path)

    venta_id = database.add_venta("2024-01-01", 10)
    database.add_dte_pendiente(venta_id=venta_id, dte_json={}, modo="2")

    venta = database.get_venta_by_id(venta_id)
    estado, envio = FacturacionTab._detectar_estado_factura(
        venta,
        None,
        None,
        database.cursor,
        venta_id=venta_id,
    )

    assert estado == "Contingencia"
    assert envio == "Pendiente de envío"
