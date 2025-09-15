from db import DB


def test_registrar_envio_dte_guarda_campos():
    db = DB(":memory:")
    venta_id = db.add_venta("2024-01-01", 10)
    db.registrar_envio_dte(
        venta_id,
        "normal",
        "Procesado",
        "SELLO",
        codigo_generacion="abc",
        numero_control="DTE-01-S001P001-000000000000001",
    )
    row = db.cursor.execute(
        "SELECT codigo_generacion, numero_control, estado, sello FROM dte_envios WHERE venta_id=?",
        (venta_id,),
    ).fetchone()
    assert row["codigo_generacion"] == "ABC"
    assert row["numero_control"] == "DTE-01-S001P001-000000000000001"
    assert row["estado"] == "Procesado"
    assert row["sello"] == "SELLO"
