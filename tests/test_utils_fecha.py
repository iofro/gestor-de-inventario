from utils.fecha import normalizar_fecha_iso


def test_normalizar_fecha_iso_dd_mm_yyyy_con_hora():
    valor = "28/09/2025 10:31:54"
    assert normalizar_fecha_iso(valor) == "2025-09-28"


def test_normalizar_fecha_iso_dd_mm_yyyy_con_guiones():
    valor = "28-09-2025"
    assert normalizar_fecha_iso(valor) == "2025-09-28"


def test_normalizar_fecha_iso_slash_iso():
    valor = "2025/09/28"
    assert normalizar_fecha_iso(valor) == "2025-09-28"
