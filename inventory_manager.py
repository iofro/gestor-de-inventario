from db import DB
from PyQt5.QtCore import QAbstractTableModel, Qt
from PyQt5.QtGui import QColor
import json
from datetime import datetime, timedelta
import os
import logging

logger = logging.getLogger(__name__)

DATOS_NEGOCIO_PATH = os.path.join(os.path.dirname(__file__), "datos_negocio.json")

class InventoryManager:
    def __init__(self):
        self.db = DB()
        self.refresh_data()

    def refresh_data(self):
        self._vendedores = self.db.get_vendedores()
        self._Distribuidores = self.db.get_Distribuidores()
        self._products = self.db.get_productos()
        self._clientes = self.db.get_clientes()
        self._model = ProductTableModel(self._products, self._vendedores, self._Distribuidores)

    def get_vendedor_names(self):
        return [vend["nombre"] for vend in self._vendedores]

    def get_Distribuidor_names(self):
        return [dist["nombre"] for dist in self._Distribuidores]

    def add_producto(self, nombre, codigo, vendedor_id, Distribuidor_id, precio_compra, precio_venta_minorista, precio_venta_mayorista, stock):
        self.db.add_producto(nombre, codigo, vendedor_id, Distribuidor_id, precio_compra, precio_venta_minorista, precio_venta_mayorista, stock)
        self.refresh_data()

    def edit_producto(self, producto_id, nombre, codigo, vendedor_id, Distribuidor_id, precio_compra, precio_venta_minorista, precio_venta_mayorista, stock):
        self.db.edit_producto(producto_id, nombre, codigo, vendedor_id, Distribuidor_id, precio_compra, precio_venta_minorista, precio_venta_mayorista, stock)
        self.refresh_data()

    def delete_producto(self, producto_id):
        self.db.delete_producto(producto_id)
        self.refresh_data()

    def filter_products(self, vendedor_nombre=None, Distribuidor_nombre=None, search=""):
        vendedor_id = None
        Distribuidor_id = None
        for vend in self._vendedores:
            if vend["nombre"] == vendedor_nombre:
                vendedor_id = vend["id"]
                break
        for dist in self._Distribuidores:
            if dist["nombre"] == Distribuidor_nombre:
                Distribuidor_id = dist["id"]
                break
        self._products = self.db.get_productos(vendedor_id=vendedor_id, Distribuidor_id=Distribuidor_id, search=search)
        self._model.update_data(self._products)

    def get_products_model(self):
        return self._model

    def get_vendedor_id_by_name(self, nombre):
        for vend in self._vendedores:
            if vend["nombre"] == nombre:
                return vend["id"]
        return None

    def get_Distribuidor_id_by_name(self, nombre):
        for dist in self._Distribuidores:
            if dist["nombre"] == nombre:
                return dist["id"]
        return None

    def aumentar_stock(self, producto_id, cantidad):
        self.db.aumentar_stock(producto_id, cantidad)
        self.refresh_data()

    def exportar_inventario_json(self, filename, tab_order=None):
        datos_negocio = {}
        if os.path.exists(DATOS_NEGOCIO_PATH):
            try:
                with open(DATOS_NEGOCIO_PATH, "r", encoding="utf-8") as f:
                    datos_negocio = json.load(f)
            except Exception:
                logger.exception("Failed to parse %s", DATOS_NEGOCIO_PATH)

        def write_array(key, iterator):
            nonlocal first_section
            if not first_section:
                f.write(",\n")
            f.write(f'"{key}":[')
            first_item = True
            for item in iterator:
                if not first_item:
                    f.write(",")
                json.dump(item, f, ensure_ascii=False)
                first_item = False
            f.write("]")
            first_section = False

        with open(filename, "w", encoding="utf-8") as f:
            first_section = True
            f.write("{")
            write_array("productos", self._products)
            write_array("vendedores", (dict(v) for v in self._vendedores))
            write_array("Distribuidores", (dict(v) for v in self._Distribuidores))
            write_array("clientes", (dict(c) for c in self._clientes))
            write_array(
                "ventas",
                (dict(v) for v in self.db.cursor.execute("SELECT * FROM ventas")),
            )
            write_array(
                "compras",
                (dict(c) for c in self.db.cursor.execute("SELECT * FROM compras")),
            )
            write_array(
                "movimientos",
                (dict(m) for m in self.db.cursor.execute("SELECT * FROM movimientos")),
            )
            write_array(
                "detalles_venta",
                (dict(d) for d in self.db.cursor.execute("SELECT * FROM detalles_venta")),
            )
            write_array(
                "detalles_compra",
                (dict(d) for d in self.db.cursor.execute("SELECT * FROM detalles_compra")),
            )
            if datos_negocio:
                f.write(",\n\"datos_negocio\":")
                json.dump(datos_negocio, f, ensure_ascii=False)
            else:
                f.write(",\n\"datos_negocio\":{}")
            write_array(
                "trabajadores",
                (dict(t) for t in self.db.cursor.execute("SELECT * FROM trabajadores")),
            )
            write_array(
                "ventas_credito_fiscal",
                (dict(v) for v in self.db.cursor.execute("SELECT * FROM ventas_credito_fiscal")),
            )
            if tab_order is not None:
                f.write(",\n\"tab_order\":")
                json.dump(tab_order, f, ensure_ascii=False)
            f.write("}")

    def importar_inventario_json(self, filename):
        with open(filename, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.db.limpiar_productos()
        self.db.limpiar_vendedores()
        self.db.limpiar_Distribuidores()
        self.db.limpiar_ventas_credito_fiscal()
        try:
            self.db.cursor.execute("DELETE FROM clientes")
            self.db.cursor.execute("DELETE FROM ventas")
            self.db.cursor.execute("DELETE FROM detalles_venta")
            self.db.cursor.execute("DELETE FROM compras")
            self.db.cursor.execute("DELETE FROM detalles_compra")
            self.db.cursor.execute("DELETE FROM movimientos")
            self.db.cursor.execute("DELETE FROM trabajadores")
            self.db.conn.commit()
        except Exception:
            pass

        vendedor_id_map = {}
        Distribuidor_id_map = {}
        producto_id_map = {}
        cliente_id_map = {}
        venta_id_map = {}
        compra_id_map = {}
        trabajador_id_map = {}

        # --- Distribuidores primero ---
        for v in data.get("Distribuidores", []):
            self.db.add_Distribuidor_detallado(v)
            self.db.cursor.execute("SELECT id FROM Distribuidores WHERE nombre=? ORDER BY id DESC LIMIT 1", (v["nombre"],))
            new_id = self.db.cursor.fetchone()["id"]
            Distribuidor_id_map[v["id"]] = new_id

        # --- Vendedores después, usando el mapeo correcto ---
        for vend in data.get("vendedores", []):
            dist_id = vend.get("Distribuidor_id")
            new_dist_id = Distribuidor_id_map.get(dist_id) if dist_id is not None else None
            self.db.add_vendedor(
                vend["nombre"],
                vend.get("descripcion", ""),
                new_dist_id,
                vend.get("codigo"),
                vend.get("dui"),

            )
            self.db.cursor.execute("SELECT id FROM vendedores WHERE nombre=? ORDER BY id DESC LIMIT 1", (vend["nombre"],))
            new_id = self.db.cursor.fetchone()["id"]
            vendedor_id_map[vend["id"]] = new_id

        for t in data.get("trabajadores", []):
            self.db.add_trabajador(t)
            trabajador_id_map[t.get("id")] = self.db.cursor.lastrowid

        # Productos
        for p in data.get("productos", []):
            vend = vendedor_id_map.get(p.get("vendedor_id"))
            dist = Distribuidor_id_map.get(p.get("Distribuidor_id"))
            self.db.add_producto(
                p.get("nombre", ""),
                p.get("codigo", ""),
                vend,
                dist,
                p.get("precio_compra", 0),
                p.get("precio_venta_minorista", 0),
                p.get("precio_venta_mayorista", 0),
                p.get("stock", 0)
            )
            new_id = self.db.cursor.lastrowid  # Usa el ID real insertado, no busques por nombre
            producto_id_map[p["id"]] = new_id

        # Clientes
        for c in data.get("clientes", []):
            self.db.add_cliente(
                c.get("nombre", ""),
                c.get("nrc", ""),
                c.get("nit", ""),
                c.get("dui", ""),
                c.get("giro", ""),
                c.get("telefono", ""),
                c.get("email", ""),
                c.get("direccion", ""),
                c.get("departamento", ""),
                c.get("municipio", ""),
                c.get("codigo")
            )
            self.db.cursor.execute("SELECT id FROM clientes WHERE nombre=? ORDER BY id DESC LIMIT 1", (c["nombre"],))
            new_id = self.db.cursor.fetchone()["id"]
            cliente_id_map[c["id"]] = new_id

        # Ventas
        for v in data.get("ventas", []):
            cliente_id = cliente_id_map.get(v.get("cliente_id"))
            Distribuidor_id = Distribuidor_id_map.get(v.get("Distribuidor_id"))
            vendedor_id = trabajador_id_map.get(v.get("vendedor_id")) if v.get("vendedor_id") is not None else None
            if vendedor_id is None and v.get("vendedor_id") is not None:
                vendedor_id = vendedor_id_map.get(v.get("vendedor_id"))

            extra = v.get("extra")
            if isinstance(extra, str):
                try:
                    extra = json.loads(extra)
                except Exception:
                    pass
            extra_json = json.dumps(extra) if extra is not None else None

            estado = v.get("estado", "Pagada")
            self.db.cursor.execute(
                "INSERT INTO ventas (id, fecha, total, cliente_id, Distribuidor_id, vendedor_id, extra, estado) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    v.get("id"),
                    v.get("fecha", ""),
                    v.get("total", 0),
                    cliente_id,
                    Distribuidor_id,
                    vendedor_id,
                    extra_json,
                    estado,
                ),
            )
            venta_id_map[v["id"]] = v.get("id")

        # ensure AUTOINCREMENT counters are updated
        max_venta_id = self.db.cursor.execute("SELECT MAX(id) FROM ventas").fetchone()[0] or 0
        self.db.cursor.execute(
            "UPDATE sqlite_sequence SET seq=? WHERE name='ventas'", (max_venta_id,)
        )

        # Compras
        for c in data.get("compras", []):
            Distribuidor_id = Distribuidor_id_map.get(c.get("Distribuidor_id")) if c.get("Distribuidor_id") is not None else None
            vendedor_id = vendedor_id_map.get(c.get("vendedor_id")) if c.get("vendedor_id") is not None else None
            comision_pct = c.get("comision_pct", 0)
            comision_monto = c.get("comision_monto", 0)
            self.db.cursor.execute(
                "INSERT INTO compras (fecha, producto_id, cantidad, precio_unitario, total, Distribuidor_id, comision_pct, comision_monto, vendedor_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    c.get("fecha", ""),
                    None,   # <-- SIEMPRE None
                    0,      # <-- SIEMPRE 0
                    0,      # <-- SIEMPRE 0
                    c.get("total", 0),
                    Distribuidor_id,
                    comision_pct,
                    comision_monto,
                    vendedor_id
                )
            )
            new_id = self.db.cursor.lastrowid
            compra_id_map[c["id"]] = new_id

        # Detalles de venta
        for d in data.get("detalles_venta", []):
            venta_id = venta_id_map.get(d.get("venta_id"))
            producto_id = producto_id_map.get(d.get("producto_id"))
            vendedor_id = None
            if d.get("vendedor_id") is not None:
                vendedor_id = trabajador_id_map.get(d.get("vendedor_id"))
                if vendedor_id is None:
                    vendedor_id = vendedor_id_map.get(d.get("vendedor_id"))
            if venta_id and producto_id:
                self.db.cursor.execute(
                    "INSERT INTO detalles_venta (venta_id, producto_id, cantidad, precio_unitario, descuento, descuento_tipo, iva, comision, iva_tipo, tipo_fiscal, extra, precio_con_iva, vendedor_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        venta_id,
                        producto_id,
                        d.get("cantidad", 0),
                        d.get("precio_unitario", 0),
                        d.get("descuento", 0),
                        d.get("descuento_tipo", ""),
                        d.get("iva", 0),
                        d.get("comision", 0),
                        d.get("iva_tipo", ""),
                        d.get("tipo_fiscal", "Gravada"),
                        d.get("extra", None),
                        d.get("precio_con_iva", 0),
                        vendedor_id
                    )
                )

        # Detalles de compra
        for d in data.get("detalles_compra", []):
            compra_id = compra_id_map.get(d.get("compra_id"))
            producto_id = producto_id_map.get(d.get("producto_id"))
            if compra_id and producto_id:
                self.db.add_detalle_compra(
                    compra_id,
                    producto_id,
                    d.get("cantidad", 0),
                    d.get("precio_unitario", 0),
                    d.get("fecha_vencimiento", ""),
                    d.get("descuento", 0),
                    d.get("descuento_tipo", ""),
                    d.get("iva", 0),
                    d.get("iva_tipo", ""),
                    d.get("comision_pct", 0),
                    d.get("comision_monto", 0),
                    d.get("comision_tipo", "")
            )

        # Movimientos (opcional, si tienes movimientos)
        for m in data.get("movimientos", []):
            producto_id = producto_id_map.get(m.get("producto_id"))
            self.db.cursor.execute(
                "INSERT INTO movimientos (fecha, tipo, producto_id, cantidad, motivo, usuario) VALUES (?, ?, ?, ?, ?, ?)",
                (m.get("fecha", ""), m.get("tipo", ""), producto_id, m.get("cantidad", 0), m.get("motivo", ""), m.get("usuario", ""))
            )

        self.db.conn.commit()
        self.refresh_data()
        # --- BLOQUE MODIFICADO PARA DATOS DEL NEGOCIO ---
        datos_negocio = data.get("datos_negocio", None)
        datos_path = DATOS_NEGOCIO_PATH
        if datos_negocio:
            with open(datos_path, "w", encoding="utf-8") as f:
                json.dump(datos_negocio, f, ensure_ascii=False, indent=2)
        elif os.path.exists(datos_path):
            # Si no hay datos del negocio en el inventario, elimina el archivo local
            os.remove(datos_path)

        # --- AGREGA DESPUÉS DE IMPORTAR VENTAS ---
        for vcf in data.get("ventas_credito_fiscal", []):
            extra = vcf.get("extra")
            extra_json = json.dumps(extra) if extra is not None else None
            self.db.cursor.execute(
                """
                INSERT INTO ventas_credito_fiscal (
                    venta_id, cliente_id, nrc, nit, giro, no_remision, orden_no, condicion_pago,
                    venta_a_cuenta_de, documento_venta_a_cuenta, fecha_remision_anterior, fecha_remision,
                    sumas, iva, subtotal, total_letras, descuentos, extra, ventas_exentas, ventas_no_sujetas
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    venta_id_map.get(vcf.get("venta_id")),
                    cliente_id_map.get(vcf.get("cliente_id")),
                    vcf.get("nrc"),
                    vcf.get("nit"),
                    vcf.get("giro"),
                    vcf.get("no_remision"),
                    vcf.get("orden_no"),
                    vcf.get("condicion_pago"),
                    vcf.get("venta_a_cuenta_de"),
                    vcf.get("documento_venta_a_cuenta"),
                    vcf.get("fecha_remision_anterior"),
                    vcf.get("fecha_remision"),
                    vcf.get("sumas", 0),
                    vcf.get("iva", 0),
                    vcf.get("subtotal", 0),
                    vcf.get("total_letras", ""),
                    vcf.get("descuentos", 0),
                    extra_json,
                    vcf.get("ventas_exentas", 0),
                    vcf.get("ventas_no_sujetas", 0),
                ),
            )
        self.db.conn.commit()
        self.refresh_data()
        return data

    def add_Distribuidor(self, nombre):
        self.db.add_Distribuidor(nombre)
        self.refresh_data()

    def add_vendedor(self, nombre, Distribuidor_id=None, codigo=None, dui=None):
        self.db.add_vendedor(nombre, descripcion="", Distribuidor_id=Distribuidor_id, codigo=codigo, dui=dui)

        self.refresh_data()

    def add_cliente(
        self,
        nombre,
        nrc,
        nit,
        dui,
        giro,
        telefono,
        email,
        direccion,
        departamento,
        municipio,
        codigo=None,
    ):
        """Add a new client and refresh the cached lists."""

        self.db.add_cliente(
            nombre,
            nrc,
            nit,
            dui,
            giro,
            telefono,
            email,
            direccion,
            departamento,
            municipio,
            codigo=codigo,
        )
        self.refresh_data()

    def update_cliente(
        self,
        cliente_id,
        codigo,
        nombre,
        nrc,
        nit,
        dui,
        giro,
        telefono,
        email,
        direccion,
        departamento,
        municipio,
    ):
        """Update an existing client and refresh the cached lists."""

        self.db.update_cliente(
            cliente_id,
            codigo,
            nombre,
            nrc,
            nit,
            dui,
            giro,
            telefono,
            email,
            direccion,
            departamento,
            municipio,
        )
        self.refresh_data()

    def delete_cliente(self, cliente_id):
        """Delete a client and refresh the cached lists."""

        self.db.delete_cliente(cliente_id)
        self.refresh_data()

    def limpiar_inventario(self):
        self.db.limpiar_productos()
        self.db.limpiar_vendedores()
        self.db.limpiar_Distribuidores()
        self.refresh_data()

    def registrar_venta_detallada(self, venta_data):
        self.db.add_venta_detallada(venta_data)
        self.refresh_data()

class ProductTableModel(QAbstractTableModel):
    def __init__(self, data, vendedores, Distribuidores):
        super().__init__()
        # Agrega "Comisión" si quieres mostrarla
        self.headers = ["Nombre", "Código", "Precio", "Stock"]  # o ["Nombre", "Código", "Precio", "Stock", "Comisión"]
        self._data = data
        self._vendedores = {vend["id"]: vend["nombre"] for vend in vendedores}
        self._Distribuidores = {dist["id"]: dist["nombre"] for dist in Distribuidores}

    def update_data(self, data):
        self.beginResetModel()
        self._data = data
        self.endResetModel()

    def rowCount(self, parent=None):
        return len(self._data)

    def columnCount(self, parent=None):
        return len(self.headers)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self._data[index.row()]
        col = index.column()
        if role == Qt.DisplayRole:
            if col == 0:
                return row.get("nombre", "")
            elif col == 1:
                return row.get("codigo", "")
            elif col == 2:
                precio = row.get("precio_venta_minorista", 0) or 0
                return f"${precio:.2f}"
            elif col == 3:
                return row.get("stock", 0)
            # Si agregas comisión:
            # elif col == 4:
            #     return f"{row.get('comision_base', 0)}%"  # O el campo que corresponda
        elif role == Qt.BackgroundRole and col == 3:
            stock = row.get("stock", 0)
            if stock < 5:
                return QColor("red")
            elif stock < 10:
                return QColor("orange")
            elif stock < 25:
                return QColor("yellow")
            else:
                return QColor("lightgreen")
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.headers[section]
        return None

class LoteTableModel(QAbstractTableModel):
    def __init__(self, detalles_compra, productos, Distribuidores, db=None):
        super().__init__()
        self.headers = ["Producto", "Código", "Cantidad", "Precio compra", "Distribuidor", "Vencimiento", "Comisión"]
        self._data = detalles_compra
        self._productos = {p["id"]: p for p in productos}
        self._Distribuidores = {d["id"]: d["nombre"] for d in Distribuidores}
        self._compra_distribuidores = {}

        # Prefetch distributor information if a DB instance is provided
        if db is not None:
            compra_ids = {d.get("compra_id") for d in detalles_compra if d.get("compra_id")}
            if compra_ids:
                placeholders = ",".join("?" * len(compra_ids))
                db.cursor.execute(
                    f"SELECT id, Distribuidor_id FROM compras WHERE id IN ({placeholders})",
                    tuple(compra_ids),
                )
                for row in db.cursor.fetchall():
                    self._compra_distribuidores[row["id"]] = self._Distribuidores.get(
                        row["Distribuidor_id"],
                        "Desconocido",
                    )

    def rowCount(self, parent=None):
        return len(self._data)

    def columnCount(self, parent=None):
        return len(self.headers)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self._data[index.row()]
        col = index.column()
        if role == Qt.DisplayRole:
            producto = self._productos.get(row["producto_id"], {})
            if col == 0:
                return producto.get("nombre", "")
            elif col == 1:
                return producto.get("codigo", "")
            elif col == 2:
                return row.get("cantidad", 0)
            elif col == 3:
                return f"${row.get('precio_unitario', 0):.2f}"
            elif col == 4:
                compra_id = row.get("compra_id")
                return self._compra_distribuidores.get(
                    compra_id, "Desconocido"
                )
            elif col == 5:
                return row.get("fecha_vencimiento", "")
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.headers[section]
        return None