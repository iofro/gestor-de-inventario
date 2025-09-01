from types import SimpleNamespace

import facturacion_tab
from db import DB


def test_open_pdf(monkeypatch, qt_app, tmp_path):
    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_text("PDF")

    db = DB(":memory:")
    man = SimpleNamespace(db=db, _clientes=[], _Distribuidores=[])
    tab = facturacion_tab.FacturacionTab(man)

    monkeypatch.setattr(tab, "_selected_entry", lambda: {"row_type": "orphan", "pdf": str(pdf_path)})

    opened = {}

    def fake_open(url):
        opened["path"] = url.toLocalFile()
        return True

    monkeypatch.setattr(facturacion_tab.QDesktopServices, "openUrl", fake_open)

    tab.open_pdf()

    assert opened["path"] == str(pdf_path)
