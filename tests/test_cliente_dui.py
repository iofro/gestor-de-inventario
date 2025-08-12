from db import DB


def test_get_clientes_returns_dui():
    db = DB(":memory:")
    dui = "01234567-8"
    db.add_cliente("Juan", "", "", dui, "", "", "", "", "", "")
    clientes = db.get_clientes()
    assert clientes[0]["dui"] == dui


def test_get_clientes_search_by_dui():
    db = DB(":memory:")
    dui = "01234567-8"
    db.add_cliente("Juan", "", "", dui, "", "", "", "", "", "")
    clientes = db.get_clientes(search="01234567")
    assert len(clientes) == 1
    assert clientes[0]["dui"] == dui
