from pathlib import PureWindowsPath
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


def test_open_pdf_windows_fallback(monkeypatch):
    from utils import printing

    class DummyWindowsPath(PureWindowsPath):
        def resolve(self):  # type: ignore[override]
            return self

    monkeypatch.setattr(printing, "Path", DummyWindowsPath)
    monkeypatch.setattr(printing.sys, "platform", "win32")

    def failing_startfile(path):
        raise OSError("boom")

    monkeypatch.setattr(printing.os, "startfile", failing_startfile, raising=False)

    opened = {}

    def fake_webbrowser_open(url, new=0):
        opened["url"] = url
        opened["new"] = new
        return True

    monkeypatch.setattr(printing.webbrowser, "open", fake_webbrowser_open)

    windows_path = "C:/Users/test/doc.pdf"
    assert printing.open_pdf_cross_platform(windows_path) is True
    assert opened["url"] == DummyWindowsPath(windows_path).as_uri()
    assert opened["new"] == 2
