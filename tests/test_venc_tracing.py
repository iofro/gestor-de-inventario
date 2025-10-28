import json
import os
import json
import os
from pathlib import Path

import pytest

from factura_sv import generar_factura_electronica_pdf


@pytest.fixture(autouse=True)
def cleanup_debug():
    debug_file = Path(".debug/pdf_meta_items.json")
    if debug_file.exists():
        debug_file.unlink()
    yield
    if debug_file.exists():
        debug_file.unlink()


def _run_pdf(detalles, tmp_path, *, force_raw=False):
    output_pdf = tmp_path / "out.pdf"
    venta = {
        "total_letras": "",
        "sumas": 0,
        "total": 0,
        "subTotalVentas": 0,
        "ventas_exentas": 0,
        "ventas_no_sujetas": 0,
        "ventas_gravadas": 0,
    }
    cliente = {"nombre": "Cliente Test"}
    distribuidor = {"nombre": "Distribuidor Test"}

    os.environ["PDF_META_DEBUG"] = "1"
    os.environ["PDF_META_TRACE"] = "1"
    os.environ["PDF_META_DUMP"] = "1"
    if force_raw:
        os.environ["PDF_META_FORCE_RAW_VENC"] = "1"
    else:
        os.environ.pop("PDF_META_FORCE_RAW_VENC", None)

    generar_factura_electronica_pdf(
        venta,
        detalles,
        cliente,
        distribuidor,
        tipo_documento="Crédito Fiscal",
        archivo=str(output_pdf),
        datos_negocio={},
        codigo_generacion="TEST-CODE",
        numero_control="NC-001",
        fecha_generacion="01/01/2024",
    )

    debug_file = Path(".debug/pdf_meta_items.json")
    assert debug_file.exists(), "El volcado de depuración no se generó"
    with debug_file.open("r", encoding="utf-8") as fh:
        data = json.load(fh)

    os.environ.pop("PDF_META_DEBUG", None)
    os.environ.pop("PDF_META_TRACE", None)
    os.environ.pop("PDF_META_DUMP", None)
    os.environ.pop("PDF_META_FORCE_RAW_VENC", None)

    return data


def test_vencimiento_tracing_variants(tmp_path):
    detalles = [
        {
            "descripcion": "Producto fecha ISO",
            "cantidad": 1,
            "precio_unitario": 1,
            "ventas_gravadas": 1,
            "extra": "Lote: X | Vence: 2025-10-27",
        },
        {
            "descripcion": "Producto fecha DMY",
            "cantidad": 1,
            "precio_unitario": 1,
            "ventas_gravadas": 1,
            "extra": {"vencimiento": "27/10/2025"},
        },
        {
            "descripcion": "Producto fecha $date",
            "cantidad": 1,
            "precio_unitario": 1,
            "ventas_gravadas": 1,
            "extra": {"obj": {"lote": "L1", "fv": {"$date": "2025-10-27"}}},
        },
        {
            "descripcion": "Producto VTO compacto",
            "cantidad": 1,
            "precio_unitario": 1,
            "ventas_gravadas": 1,
            "extra": "VTO 2310",
        },
        {
            "descripcion": "Producto EXP compacto",
            "cantidad": 1,
            "precio_unitario": 1,
            "ventas_gravadas": 1,
            "extra": "EXP: 202510",
        },
        {
            "descripcion": "Producto año/mes",
            "cantidad": 1,
            "precio_unitario": 1,
            "ventas_gravadas": 1,
            "extra": "Fecha=2025/10",
        },
        {
            "descripcion": "Producto epoch 10",
            "cantidad": 1,
            "precio_unitario": 1,
            "ventas_gravadas": 1,
            "extra": "Expiry: 1698432000",
        },
        {
            "descripcion": "Producto epoch 13",
            "cantidad": 1,
            "precio_unitario": 1,
            "ventas_gravadas": 1,
            "extra": "Expiry: 1698432000000",
        },
        {
            "descripcion": "Producto descripción",
            "cantidad": 1,
            "precio_unitario": 1,
            "ventas_gravadas": 1,
            "extra": None,
        },
    ]
    detalles[-1]["descripcion"] = "Medicamento Vence: 2025-10-27"

    rows = _run_pdf(detalles, tmp_path)

    assert len(rows) == len(detalles)
    for row in rows:
        assert row["where_found"], f"where_found vacío para índice {row['index']}"
        if row["normalized_value"]:
            assert row["normalized_value"].count("/") == 2
            dd, mm, yyyy = row["normalized_value"].split("/")
            assert len(dd) == 2 and len(mm) == 2 and len(yyyy) == 4
        else:
            assert row["raw_value"], "Sin valor crudo cuando falta normalización"

    expected = {
        0: "27/10/2025",
        1: "27/10/2025",
        2: "27/10/2025",
        3: "01/10/2023",
        4: "01/10/2025",
        5: "01/10/2025",
        6: "27/10/2023",
        7: "27/10/2023",
        8: "27/10/2025",
    }

    for row in rows:
        expected_norm = expected[row["index"]]
        assert row["normalized_value"] == expected_norm


def test_force_raw_when_normalization_fails(tmp_path):
    detalles = [
        {
            "descripcion": "Producto sin formato",
            "cantidad": 1,
            "precio_unitario": 1,
            "ventas_gravadas": 1,
            "extra": "Vencimiento: INDEF",
        }
    ]

    rows = _run_pdf(detalles, tmp_path, force_raw=True)
    assert rows[0]["raw_value"] == "INDEF"
    assert rows[0]["where_found"]
    assert rows[0]["normalized_value"] in (None, "INDEF")
    assert rows[0]["raw_value"]
    assert rows[0]["index"] == 0
    assert rows[0]["raw_value"] in rows[0]["all_candidates"]
