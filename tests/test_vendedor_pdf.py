import json
import inventory_manager as im
import estado_cuenta_pdf as pdf

class MemoryDB(im.DB):
    def __init__(self):
        super().__init__(db_name=":memory:")

def test_vendedor_pdf_without_trabajador(tmp_path, monkeypatch):
    monkeypatch.setattr(im, "DB", MemoryDB)
    manager = im.InventoryManager()
    data = {
        "Distribuidores": [],
        "vendedores": [{"id": 1, "nombre": "V1", "codigo": "V001"}],
        "clientes": [{"id": 1, "nombre": "C1", "codigo": "C001"}],
        "productos": [{"id": 1, "nombre": "P1", "codigo": "P001", "precio_compra": 0, "precio_venta_minorista": 0, "precio_venta_mayorista": 0, "stock": 10}],
        "ventas": [{"id": 1, "fecha": "2024-01-01", "total": 10, "cliente_id": 1, "vendedor_id": 1}],
        "detalles_venta": [
            {"venta_id": 1, "producto_id": 1, "cantidad": 1, "precio_unitario": 10, "descuento": 0, "descuento_tipo": "", "iva": 0, "comision": 0, "iva_tipo": "", "tipo_fiscal": "Gravada", "extra": None, "precio_con_iva": 10, "vendedor_id": 1}
        ],
    }
    path = tmp_path / "inv.json"
    path.write_text(json.dumps(data))
    manager.importar_inventario_json(str(path))
    vend_id = manager.db.get_vendedores()[0]["id"]
    pdf_path = tmp_path / "rep.pdf"
    pdf.generar_reporte_vendedor_pdf(manager.db, vend_id, "2024-01-01", "2024-12-31", archivo=str(pdf_path))
    assert pdf_path.exists()
