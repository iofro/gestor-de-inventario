import sys
import types
from db import DB


def test_export_import_transmission_records(monkeypatch, tmp_path):
    qtcore = types.SimpleNamespace(
        QAbstractTableModel=object,
        Qt=types.SimpleNamespace(
            DisplayRole=0, Horizontal=1, BackgroundRole=2
        ),
    )
    qtgui = types.SimpleNamespace(QColor=object)
    pyqt5 = types.SimpleNamespace(QtCore=qtcore, QtGui=qtgui)
    sys.modules.setdefault("PyQt5", pyqt5)
    sys.modules["PyQt5.QtCore"] = qtcore
    sys.modules["PyQt5.QtGui"] = qtgui

    import inventory_manager

    def dummy_refresh(self):
        self._vendedores = self.db.get_vendedores()
        self._Distribuidores = self.db.get_Distribuidores()
        self._vendedores_by_id = {v["id"]: v["nombre"] for v in self._vendedores}
        self._Distribuidores_by_id = {
            d["id"]: d["nombre"] for d in self._Distribuidores
        }
        self._products = self.db.get_productos(
            vendedor_id=self._filter_vendedor_id,
            Distribuidor_id=self._filter_Distribuidor_id,
            search=self._filter_search,
        )
        self._clientes = self.db.get_clientes()
        self._model = None

    monkeypatch.setattr(
        inventory_manager.InventoryManager, "refresh_data", dummy_refresh
    )

    man1 = inventory_manager.InventoryManager(DB(":memory:"))
    db = man1.db
    db.add_Distribuidor("D1")
    dist = db.cursor.lastrowid
    db.add_vendedor("V1", Distribuidor_id=dist)
    vend = db.cursor.lastrowid
    db.add_cliente("Cliente", "", "", "", "", "", "", "", "", "")
    cliente_id = db.cursor.lastrowid
    db.add_producto("Prod", "P1", None,  vend, dist, 1, 2, 3, 5)
    venta_id = db.add_venta(
        "2024-01-01", 10, cliente_id=cliente_id, vendedor_id=vend, Distribuidor_id=dist
    )
    db.cursor.execute(
        "INSERT INTO dte_envios (venta_id, modo, estado, sello, fecha_hora, respuesta) VALUES (?, ?, ?, ?, ?, ?)",
        (venta_id, "envio", "PROCESADO", "abc", "2024-01-01T00:00:00", "ok"),
    )
    db.cursor.execute(
        "INSERT INTO notas (venta_id, tipo, fecha, monto, motivo, detalles) VALUES (?, ?, ?, ?, ?, ?)",
        (venta_id, "NC", "2024-01-02", 1.23, "motivo", "det"),
    )
    db.cursor.execute(
        "INSERT INTO facturas_pdf (venta_id, tipo, ruta, fecha_creacion) VALUES (?, ?, ?, ?)",
        (venta_id, "fiscal", "/tmp/factura.pdf", "2024-01-01"),
    )
    db.cursor.execute(
        "INSERT INTO tickets_pdf (venta_id, ruta, fecha_creacion) VALUES (?, ?, ?)",
        (venta_id, "/tmp/ticket.pdf", "2024-01-01"),
    )
    db.conn.commit()
    man1.refresh_data()
    export_file = tmp_path / "export.json"
    man1.exportar_inventario_json(str(export_file))

    man2 = inventory_manager.InventoryManager(DB(":memory:"))
    man2.importar_inventario_json(str(export_file))

    cur = man2.db.cursor
    row = cur.execute(
        "SELECT modo, estado, sello, fecha_hora, respuesta FROM dte_envios"
    ).fetchone()
    assert (
        row["modo"],
        row["estado"],
        row["sello"],
        row["fecha_hora"],
        row["respuesta"],
    ) == ("envio", "PROCESADO", "abc", "2024-01-01T00:00:00", "ok")

    row = cur.execute(
        "SELECT tipo, fecha, monto, motivo, detalles FROM notas"
    ).fetchone()
    assert (
        row["tipo"],
        row["fecha"],
        row["monto"],
        row["motivo"],
        row["detalles"],
    ) == ("NC", "2024-01-02", 1.23, "motivo", "det")

    row = cur.execute(
        "SELECT tipo, ruta, fecha_creacion FROM facturas_pdf"
    ).fetchone()
    assert (
        row["tipo"],
        row["ruta"],
        row["fecha_creacion"],
    ) == ("fiscal", "/tmp/factura.pdf", "2024-01-01")

    row = cur.execute(
        "SELECT ruta, fecha_creacion FROM tickets_pdf"
    ).fetchone()
    assert (row["ruta"], row["fecha_creacion"]) == (
        "/tmp/ticket.pdf",
        "2024-01-01",
    )
