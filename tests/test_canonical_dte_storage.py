import json
import logging
from pathlib import Path

import pytest

import paths
import utils.docs as docs
import utils.doc_generation as doc_gen
try:
    import facturacion_tab  # type: ignore
except Exception:  # pragma: no cover - optional for headless testing
    facturacion_tab = None


class FakeDB:
    def __init__(self):
        self._ventas = []
        self.detalles = {}
        self.added_pdfs = []
        self.extra_updates = []

    def get_ventas(self):
        return self._ventas

    def get_venta_credito_fiscal(self, venta_id):
        return None

    def get_detalles_venta(self, venta_id):
        return self.detalles.get(venta_id, [])

    def get_trabajador(self, trabajador_id):
        return None

    def add_factura_pdf(self, venta_id, tipo_doc, path):
        self.added_pdfs.append((venta_id, tipo_doc, path))

    def add_dte_pendiente(self, *a, **k):
        pass

    def update_venta_extra(self, venta_id, data):
        self.extra_updates.append((venta_id, data))

    def next_dte_correlativo(self, tipo, sucursal, punto):
        return 1


def _patch_canonical_environment(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "USER_DATA_DIR", tmp_path)
    # Refresh canonical directories after overriding USER_DATA_DIR
    for attr, tipo in [
        ("FACTURAS_CONSUMIDOR_FINAL_DIR", "ConsumidorFinal"),
        ("FACTURAS_CREDITO_FISCAL_DIR", "CreditoFiscal"),
        ("NOTAS_CREDITO_DIR", "NotaCredito"),
        ("NOTAS_DEBITO_DIR", "NotaDebito"),
        ("NOTAS_REMISION_DIR", "NotaRemision"),
    ]:
        monkeypatch.setattr(paths, attr, str(paths.get_canonical_dte_dir(tipo)), raising=False)
    monkeypatch.setattr(docs, "BASE_DIR", paths.user_data_path())
    if facturacion_tab is not None:
        for attr in [
            "NOTAS_CREDITO_OUTPUT_DIR",
            "NOTAS_DEBITO_OUTPUT_DIR",
            "NOTAS_REMISION_OUTPUT_DIR",
            "NOTAS_CREDITO_DIR",
            "NOTAS_DEBITO_DIR",
            "NOTAS_REMISION_DIR",
        ]:
            if hasattr(facturacion_tab, attr):
                tipo = (
                    "NotaCredito"
                    if "CREDITO" in attr
                    else "NotaDebito"
                    if "DEBITO" in attr
                    else "NotaRemision"
                )
                monkeypatch.setattr(
                    facturacion_tab,
                    attr,
                    str(paths.get_canonical_dte_dir(tipo)),
                    raising=False,
                )


@pytest.fixture
def canonical_env(tmp_path, monkeypatch):
    _patch_canonical_environment(monkeypatch, tmp_path)
    return tmp_path


@pytest.fixture
def fake_sign_and_save(monkeypatch, tmp_path):
    def _fake(payload, json_path, return_token=False, **_):
        path = Path(json_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
        if return_token:
            return str(path), "TOKEN"
        return str(path)

    monkeypatch.setattr(doc_gen, "sign_and_save", _fake)
    return _fake


@pytest.fixture
def fake_save_dte(monkeypatch, tmp_path):
    def _fake(data, filename):
        target = tmp_path / "pendientes" / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(data), encoding="utf-8")
        return str(target)

    monkeypatch.setattr(doc_gen.dte, "save_dte_json", _fake)
    return _fake


@pytest.fixture
def fake_versioned_state(monkeypatch):
    monkeypatch.setattr(doc_gen.versioned_dte, "save_estado", lambda *a, **k: None)


@pytest.fixture
def fake_generar_dte(monkeypatch):
    def _fake(db, venta_id, **_):
        venta = next(v for v in db.get_ventas() if v["id"] == venta_id)
        detalles = db.get_detalles_venta(venta_id)
        data = docs.build_invoice_json(venta, {}, detalles)
        ident = data.setdefault("identificacion", {})
        ident.setdefault("codigoGeneracion", "GENERACION")
        ident.setdefault("numeroControl", "CTRL-001")
        return data

    monkeypatch.setattr(doc_gen, "generar_dte_json", _fake)
    return _fake


@pytest.fixture
def fake_pdf_renderer(monkeypatch):
    def _fake(*args, archivo=None, **kwargs):
        path = Path(archivo)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"PDF")

    monkeypatch.setattr(doc_gen, "generar_factura_electronica_pdf", _fake)
    return _fake


def test_generate_invoice_files_in_canonical_dir(canonical_env, fake_sign_and_save, fake_save_dte, fake_versioned_state, fake_generar_dte, fake_pdf_renderer):
    db = FakeDB()
    venta = {"id": 1, "fecha": "2024-04-01", "total": 10}
    db._ventas.append(venta)
    db.detalles[1] = [{"cantidad": 1, "precio_unitario": 10}]
    manager = type("Manager", (), {"db": db, "_clientes": [], "_Distribuidores": []})()

    pdf_path = doc_gen.generate_invoice_pdf(manager, 1)

    canonical_dir = paths.get_canonical_dte_dir("ConsumidorFinal")
    pdf_file = Path(pdf_path)
    assert pdf_file.parent == canonical_dir
    json_file = pdf_file.with_suffix(".json")
    assert json_file.exists()
    assert pdf_file.exists()
    assert not any(pdf_file.parent.glob("*.tmp"))


def test_credit_note_files_use_canonical_dir(canonical_env, fake_sign_and_save, fake_save_dte, fake_versioned_state, fake_generar_dte, monkeypatch):
    nota_json = {
        "identificacion": {
            "tipoDte": "05",
            "fecEmi": "2024-05-10",
            "numeroControl": "DTE-05-AAA-1",
            "codigoGeneracion": "NC-001",
        }
    }
    cliente = {"nombre": "Cliente"}
    venta_data = {"total": 5, "total_letras": "CINCO"}
    detalles = []

    pdf_path, json_path = docs.get_dte_document_paths(
        nota_json["identificacion"].get("fecEmi"),
        cliente.get("nombre"),
        nota_json["identificacion"].get("numeroControl"),
        "NotaCredito",
    )

    def _fake_pdf(output_path):
        output_path.write_bytes(b"NC")

    docs.write_pdf_atomically(pdf_path, _fake_pdf)
    Path(json_path).write_text(json.dumps({"nota": nota_json, "venta": venta_data, "detalles": detalles}), encoding="utf-8")

    canonical_dir = paths.get_canonical_dte_dir("NotaCredito")
    assert Path(pdf_path).parent == canonical_dir
    assert Path(json_path).parent == canonical_dir


def test_generate_invoice_pdf_logs_and_fails_on_pdf_error(canonical_env, fake_sign_and_save, fake_save_dte, fake_versioned_state, fake_generar_dte, monkeypatch, caplog):
    db = FakeDB()
    venta = {"id": 5, "fecha": "2024-04-01", "total": 10}
    db._ventas.append(venta)
    db.detalles[5] = [{"cantidad": 1, "precio_unitario": 10}]
    manager = type("Manager", (), {"db": db, "_clientes": [], "_Distribuidores": []})()

    def _fail(*args, **kwargs):
        raise IOError("fallo render")

    monkeypatch.setattr(doc_gen, "generar_factura_electronica_pdf", _fail)
    caplog.set_level(logging.ERROR)
    with pytest.raises(IOError):
        doc_gen.generate_invoice_pdf(manager, 5)
    assert any("No se pudo escribir PDF" in rec.message for rec in caplog.records)
    assert not db.added_pdfs


def test_ensure_invoice_copies_raises_on_pdf_failure(tmp_path):
    pdf_path = tmp_path / "factura.pdf"
    json_path = tmp_path / "factura.json"
    payload = {"identificacion": {}}

    def _fail_renderer(_):
        raise IOError("sin permisos")

    with pytest.raises(IOError):
        doc_gen._ensure_invoice_copies(pdf_path, json_path, payload, _fail_renderer)


def test_ensure_invoice_copies_raises_on_json_failure(tmp_path, monkeypatch):
    pdf_path = tmp_path / "factura.pdf"
    pdf_path.write_bytes(b"PDF")
    json_path = tmp_path / "factura.json"
    payload = {"identificacion": {}}

    def _raise(*_args, **_kwargs):
        raise OSError("bloqueado")

    monkeypatch.setattr(doc_gen, "save_file", _raise)

    with pytest.raises(OSError):
        doc_gen._ensure_invoice_copies(pdf_path, json_path, payload, lambda path: path.write_bytes(b"PDF"))


def test_generate_invoice_pdf_aborts_when_json_copy_cannot_be_written(
    canonical_env,
    fake_sign_and_save,
    fake_save_dte,
    fake_versioned_state,
    fake_generar_dte,
    fake_pdf_renderer,
    monkeypatch,
):
    db = FakeDB()
    venta = {"id": 6, "fecha": "2024-04-01", "total": 10}
    db._ventas.append(venta)
    db.detalles[6] = [{"cantidad": 1, "precio_unitario": 10}]
    manager = type("Manager", (), {"db": db, "_clientes": [], "_Distribuidores": []})()

    original_path_missing = doc_gen._path_missing

    def _force_missing(path: Path) -> bool:
        if Path(path).suffix == ".json":
            return True
        return original_path_missing(path)

    def _raise_save(path, *_args, **_kwargs):
        raise OSError(f"sin permisos para {path}")

    monkeypatch.setattr(doc_gen, "_path_missing", _force_missing)
    monkeypatch.setattr(doc_gen, "save_file", _raise_save)

    with pytest.raises(OSError):
        doc_gen.generate_invoice_pdf(manager, 6)

    assert not db.added_pdfs
