import re
import dte


def test_generar_numero_control_format(db_conn):
    num1 = dte.generar_numero_control(db_conn, "01", "001", "002")
    assert num1 == "DTE-01-S001P002-000000000000001"
    assert re.fullmatch(r"DTE-\d{2}-S\d{3}P\d{3}-000000000000\d{3}", num1)
    num2 = dte.generar_numero_control(db_conn, "01", "001", "002")
    assert num2 == "DTE-01-S001P002-000000000000002"

