import pytest

try:
    from dialogs.dialogs import CompraDetalleDialog
    from utils.party_resolver import Catalogs
except ImportError as exc:  # pragma: no cover - dependency missing in test env
    pytest.skip(str(exc), allow_module_level=True)


class _DummyManager:
    def __init__(self):
        self.catalogs = Catalogs(vendors={}, distributors={}, products={}, db=None)
        self._vendedores_compra = []
        self._vendedores_compra_by_id = {1378: "Proveedor Demo"}
        self._Distribuidores = []
        self._Distribuidores_by_id = {1271: "Distribuidor Demo"}
        self._products = []
        self.db = None


class _DummyParent:
    def __init__(self, manager):
        self.manager = manager


def test_resolve_catalogs_hydrates_from_id_maps():
    manager = _DummyManager()
    parent = _DummyParent(manager)

    catalogs, db = CompraDetalleDialog._resolve_catalogs(parent, catalogs=None)

    assert db is None
    assert catalogs.vendors[1378]["nombre"] == "Proveedor Demo"
    assert catalogs.distributors[1271]["nombre"] == "Distribuidor Demo"
