from utils.fecha import fecha_iso, normalizar_fecha_iso


def test_normalizar_fecha_iso_dd_mm_yyyy_con_hora():
    valor = "28/09/2025 10:31:54"
    assert normalizar_fecha_iso(valor) == "2025-09-28"


def test_normalizar_fecha_iso_dd_mm_yyyy_con_guiones():
    valor = "28-09-2025"
    assert normalizar_fecha_iso(valor) == "2025-09-28"


def test_normalizar_fecha_iso_slash_iso():
    valor = "2025/09/28"
    assert normalizar_fecha_iso(valor) == "2025-09-28"


def test_fecha_iso_dd_mm_yyyy():
    assert fecha_iso("28/09/2025") == "2025-09-28"


def test_fecha_iso_iso_con_timezone_z():
    assert fecha_iso("2025-09-28T10:31:54Z") == "2025-09-28"


def test_fecha_iso_iso_con_offset():
    assert fecha_iso("2025-09-28T05:15:00-06:00") == "2025-09-28"


def test_fecha_iso_invalida_retorna_original():
    assert fecha_iso("fecha no valida") == "fecha no valida"
