import re

import dte


def test_generar_numero_control_format(db_conn):
    numero = dte.generar_numero_control(db_conn, "01", "001", "002")
    assert numero == "DTE-01-S001P002-000000000000001"
    assert re.fullmatch(r"DTE-\d{2}-S\d{3}P\d{3}-\d{15}", numero)
    siguiente = dte.generar_numero_control(db_conn, "01", "001", "002")
    assert siguiente.endswith("000000000000002")
