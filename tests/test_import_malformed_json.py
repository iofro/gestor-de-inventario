import inventory_manager as im
import pytest


class MemoryDB(im.DB):
    def __init__(self):
        super().__init__(db_name=":memory:")


def test_importar_json_malformado(tmp_path):
    manager = im.InventoryManager(MemoryDB())
    bad_file = tmp_path / "malformado.json"
    bad_file.write_text("{", encoding="utf-8")

    with pytest.raises(im.InventoryManagerError) as excinfo:
        manager.importar_inventario_json(str(bad_file))

    msg = str(excinfo.value)
    assert str(bad_file) in msg
    assert ("línea" in msg or "linea" in msg)
    assert "columna" in msg
