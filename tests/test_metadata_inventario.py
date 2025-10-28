import factura_sv


def test_metadata_desde_inventario_uses_inventory_provider(monkeypatch):
    detalle = {
        'extra': {
            'lote_id': 123,
            'codigo_lote': 'L123',
            'producto_id': 456,
            'registro_sanitario': 'RS-ALT',
        }
    }

    captured_kwargs = {}

    def fake_obtener_info_lote(**kwargs):
        captured_kwargs.update(kwargs)
        return {
            'lote': 'L123',
            'vencimiento': '2025-12-31',
            'registro': 'RS-99',
        }

    monkeypatch.setattr('factura_sv.obtener_info_lote', fake_obtener_info_lote)
    monkeypatch.setattr('factura_sv.formatear_fecha_vencimiento_ui', lambda value: '31/12/2025')

    metadata = factura_sv._metadata_desde_inventario(detalle)

    assert metadata == {
        'lote': 'L123',
        'vencimiento': '31/12/2025',
        'registro': 'RS-99',
    }
    assert captured_kwargs == {
        'lote_id': 123,
        'codigo_lote': 'L123',
        'producto_id': 456,
    }
