from db import DB


def test_revert_dte_correlativo_basic():
    db = DB(":memory:")
    db.set_dte_correlativo("03", "001", "001", 404)

    ok, motivo = db.revert_dte_correlativo("03", "001", "001", 404)
    assert ok
    assert motivo is None
    assert db.get_dte_correlativo("03", "001", "001") == 403


def test_revert_dte_correlativo_handles_advanced_sequence():
    db = DB(":memory:")
    # Simula un correlativo que avanzó dos veces (por ejemplo, intentos fallidos)
    db.set_dte_correlativo("03", "001", "001", 405)

    ok, motivo = db.revert_dte_correlativo("03", "001", "001", 404)
    assert ok
    assert motivo is None
    assert db.get_dte_correlativo("03", "001", "001") == 403


def test_revert_dte_correlativo_missing_entry():
    db = DB(":memory:")

    ok, motivo = db.revert_dte_correlativo("03", "001", "001", 404)
    assert not ok
    assert "No existe un correlativo" in motivo


def test_revert_dte_correlativo_lower_than_expected():
    db = DB(":memory:")
    db.set_dte_correlativo("03", "001", "001", 402)

    ok, motivo = db.revert_dte_correlativo("03", "001", "001", 404)
    assert not ok
    assert "El correlativo almacenado" in motivo
    assert db.get_dte_correlativo("03", "001", "001") == 402
