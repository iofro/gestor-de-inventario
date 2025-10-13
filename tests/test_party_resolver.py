import sqlite3

from utils.party_resolver import Catalogs, resolve_party_names


def test_resolve_party_names_uses_catalogs_and_vendor_links_distributor():
    catalogs = Catalogs(
        vendors={1: {"id": 1, "nombre": "Alice", "Distribuidor_id": 5}},
        distributors={5: {"id": 5, "nombre": "Distribuidora Central"}},
        products={},
    )
    purchase = {"id": 42, "vendedor_id": "1"}

    vendor_name, distributor_name = resolve_party_names(purchase, catalogs)

    assert vendor_name == "Alice"
    assert distributor_name == "Distribuidora Central"


def test_resolve_party_names_respects_prefilled_names():
    catalogs = Catalogs(vendors={}, distributors={}, products={})
    purchase = {
        "id": 7,
        "vendor_name": "Nombre directo",
        "distribuidor_nombre": "Proveedor directo",
        "vendedor_id": 99,
        "Distribuidor_id": 77,
    }

    vendor_name, distributor_name = resolve_party_names(purchase, catalogs)

    assert vendor_name == "Nombre directo"
    assert distributor_name == "Proveedor directo"


def test_resolve_party_names_supports_legacy_keys():
    catalogs = Catalogs(
        vendors={10: {"id": 10, "nombre": "Proveedor Actual"}},
        distributors={},
        products={},
    )
    purchase = {
        "id": 101,
        "Proveedor_id": "10",
        "proveedor": "Proveedor Histórico",
        "DistribuidorNombre": "Distribuidor Hist",
    }

    vendor_name, distributor_name = resolve_party_names(purchase, catalogs)

    assert vendor_name == "Proveedor Histórico"
    assert distributor_name == "Distribuidor Hist"


def test_resolve_party_names_queries_database_when_catalog_empty():
    conn = sqlite3.connect(":memory:")
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE vendedores (id INTEGER PRIMARY KEY, nombre TEXT)")
    cursor.execute("CREATE TABLE Distribuidores (id INTEGER PRIMARY KEY, nombre TEXT)")
    cursor.execute("INSERT INTO vendedores (id, nombre) VALUES (2, 'Base Vendedor')")
    cursor.execute("INSERT INTO Distribuidores (id, nombre) VALUES (3, 'Base Distribuidor')")
    conn.commit()

    db = type("DBProxy", (), {"cursor": cursor})()
    catalogs = Catalogs(vendors={}, distributors={}, products={}, db=db)
    purchase = {"id": 88, "vendedor_id": 2, "Distribuidor_id": 3}

    vendor_name, distributor_name = resolve_party_names(purchase, catalogs)

    conn.close()

    assert vendor_name == "Base Vendedor"
    assert distributor_name == "Base Distribuidor"
    assert catalogs.vendors[2]["nombre"] == "Base Vendedor"
    assert catalogs.distributors[3]["nombre"] == "Base Distribuidor"
