from db import DB


def test_registrar_envio_dte_guarda_campos():
    db = DB(":memory:")
    venta_id = db.add_venta("2024-01-01", 10)
    db.registrar_envio_dte(
        venta_id,
        "normal",
        "Procesado",
        "0" * 40,
        {"estado": "Procesado"},
        codigo_generacion="abc",
        numero_control="DTE-01-S001P001-000000000000001",
    )
    row = db.cursor.execute(
        """
        SELECT codigo_generacion, numero_control, estado, sello, estado_ui, estado_ui_tag
        FROM dte_envios WHERE venta_id=?
        """,
        (venta_id,),
    ).fetchone()
    assert row["codigo_generacion"] == "ABC"
    assert row["numero_control"] == "DTE-01-S001P001-000000000000001"
    assert row["estado"] == "Procesado"
    assert row["sello"] == "0" * 40
    assert row["estado_ui"] == "Enviado"
    assert row["estado_ui_tag"] == ""


def test_registrar_envio_dte_estado_ui_monotonic():
    db = DB(":memory:")
    venta_id = db.add_venta("2024-01-01", 10)
    codigo = "abc-123"

    etapas = [
        ({"estado": "Transmitido"}, "TRANSMITIDO", "Enviado", ""),
        ({"estado": "Procesado"}, "PROCESADO", "Enviado", ""),
        (
            {
                "estado": "Rechazado",
                "codigoMsg": "096",
                "descripcionMsg": "DOCUMENTO NO CUMPLE ESQUEMA JSON",
            },
            "RECHAZADO",
            "Rechazado",
            "schema",
        ),
        ({"estado": "Aceptado"}, "ACEPTADO", "Aceptado", ""),
        ({"estado": "Procesado"}, "PROCESADO", "Aceptado", ""),
    ]

    for payload, estado, esperado, tag_esperado in etapas:
        db.registrar_envio_dte(
            venta_id,
            "normal",
            estado,
            "S",
            payload,
            codigo_generacion=codigo,
        )
        row = db.cursor.execute(
            """
            SELECT estado, estado_ui, estado_ui_tag FROM dte_envios
            WHERE codigo_generacion=?
            ORDER BY id DESC LIMIT 1
            """,
            (codigo.upper(),),
        ).fetchone()
        assert row["estado_ui"] == esperado
        assert row["estado_ui_tag"] == tag_esperado


def test_registrar_envio_dte_estado_ui_por_numero_control():
    db = DB(":memory:")
    numero = "DTE-01-S001P001-000000000000009"

    db.registrar_envio_dte(
        None,
        "normal",
        "TRANSMITIDO",
        "S",
        {"estado": "Transmitido"},
        numero_control=numero,
    )
    db.registrar_envio_dte(
        None,
        "normal",
        "ACEPTADO",
        "S",
        {"estado": "Aceptado"},
        numero_control=numero,
    )

    row = db.cursor.execute(
        """
        SELECT estado_ui, estado_ui_tag, numero_control FROM dte_envios
        WHERE numero_control=?
        ORDER BY id DESC LIMIT 1
        """,
        (numero.upper(),),
    ).fetchone()

    assert row["numero_control"] == numero.upper()
    assert row["estado_ui"] == "Aceptado"
    assert row["estado_ui_tag"] == ""


def test_registrar_envio_dte_prioriza_codigo_generacion_sobre_numero_control():
    db = DB(":memory:")

    db.registrar_envio_dte(
        None,
        "normal",
        "RECHAZADO",
        "S",
        {
            "estado": "Rechazado",
            "codigoMsg": "096",
            "descripcionMsg": "DOCUMENTO NO CUMPLE ESQUEMA JSON",
        },
        codigo_generacion="abc",
        numero_control="NC-ORIG",
    )

    db.registrar_envio_dte(
        None,
        "normal",
        "PROCESADO",
        "S",
        {"estado": "Procesado"},
        numero_control="nc-dup",
    )

    db.registrar_envio_dte(
        None,
        "normal",
        "PROCESADO",
        "S",
        {"estado": "Procesado"},
        codigo_generacion="ABC",
        numero_control="nc-dup",
    )

    row = db.cursor.execute(
        """
        SELECT estado_ui, estado_ui_tag FROM dte_envios
        ORDER BY id DESC LIMIT 1
        """
    ).fetchone()

    assert row["estado_ui"] == "Rechazado"
    assert row["estado_ui_tag"] == "schema"


def test_registrar_envio_dte_fusion_por_numero_control():
    db = DB(":memory:")
    numero = "dte-01-s001p001-000000000000099"

    db.registrar_envio_dte(
        None,
        "normal",
        "RECHAZADO",
        "S",
        {
            "estado": "Rechazado",
            "codigoMsg": "014",
            "descripcionMsg": "NO EXISTE UN REGISTRO CON ESTE DATO",
        },
        numero_control=numero,
    )

    db.registrar_envio_dte(
        None,
        "normal",
        "PROCESADO",
        "S",
        {"estado": "Procesado"},
        numero_control=numero,
    )

    row = db.cursor.execute(
        """
        SELECT estado_ui, estado_ui_tag FROM dte_envios
        WHERE numero_control=?
        ORDER BY id DESC LIMIT 1
        """,
        (numero.upper(),),
    ).fetchone()

    assert row["estado_ui"] == "Rechazado"
    assert row["estado_ui_tag"] == "no_registro"
