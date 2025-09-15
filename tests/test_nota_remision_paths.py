from pathlib import Path

import facturacion_tab
from utils import docs


def test_guardar_archivos_nota_remision_uses_docs_folder(tmp_path, monkeypatch):
    folder = tmp_path / "notas_remision"
    monkeypatch.setitem(docs.FOLDERS, "NotaRemision", str(folder))

    def fake_pdf(venta, detalles, cliente, distribuidor, archivo="nota_remision.pdf", **kwargs):
        Path(archivo).write_text("PDF")

    monkeypatch.setattr(facturacion_tab, "generar_nota_remision_pdf", fake_pdf)

    nota_json = {
        "identificacion": {
            "fecEmi": "2024-05-01",
            "numeroControl": "DTE-04-ABC-1",
            "codigoGeneracion": "UUID",
        },
        "receptor": {"nombre": "Cliente"},
        "resumen": {},
        "cuerpoDocumento": [],
        "extension": {},
    }

    facturacion_tab.FacturacionTab._guardar_archivos_nota_remision(object(), nota_json)

    pdf_files = list(folder.glob("*.pdf"))
    json_files = list(folder.glob("*.json"))

    assert len(pdf_files) == 1
    assert len(json_files) == 1
    assert pdf_files[0].parent == folder
    assert json_files[0].parent == folder
    assert not (folder / "notas_remision").exists()

