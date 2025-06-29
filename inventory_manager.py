from db import DB
from PyQt5.QtCore import QAbstractTableModel, Qt
from PyQt5.QtGui import QColor
import json
from datetime import datetime, timedelta
import os

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

    def exportar_inventario_json(self, filename):
        datos_negocio = {}
        if os.path.exists("datos_negocio.json"):
            with open("datos_negocio.json", "r", encoding="utf-8") as f:
                datos_negocio = json.load(f)
        ventas_credito_fiscal = [dict(row) for row in self.db.cursor.execute("SELECT * FROM ventas_credito_fiscal")]
        data = {
            "productos": self._products,
            "vendedores": [dict(vend) for vend in self._vendedores],
            "Distribuidores": [dict(v) for v in self._Distribuidores],
            "clientes": [dict(c) for c in self._clientes],
            "ventas": [dict(v) for v in self.db.get_ventas()],
            "compras": [dict(c) for c in self.db.get_compras()],
            "movimientos": [dict(m) for m in self.db.get_movimientos()],
            "detalles_venta": [dict(d) for d in self.db.cursor.execute("SELECT * FROM detalles_venta")],
            "detalles_compra": [dict(d) for d in self.db.cursor.execute("SELECT * FROM detalles_compra")],
            "datos_negocio": datos_negocio,
            "trabajadores": [dict(t) for t in self.db.get_trabajadores()],
            "ventas_credito_fiscal": ventas_credito_fiscal,
        }
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def importar_inventario_json(self, filename):
        with open(filename, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.db.limpiar_productos()
        self.db.limpiar_vendedores()
        self.db.limpiar_Distribuidores()
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
                vend["nombre"], vend.get("descripcion", ""), new_dist_id, vend.get("codigo")
            )
            self.db.cursor.execute("SELECT id FROM vendedores WHERE nombre=? ORDER BY id DESC LIMIT 1", (vend["nombre"],))
            new_id = self.db.cursor.fetchone()["id"]
            vendedor_id_map[vend["id"]] = new_id

        for t in data.get("trabajadores", []):
            self.db.add_trabajador(t)

        # Productos
        for p in data.get("productos", []):
            self.db.add_producto(
                p.get("nombre", ""),
                p.get("codigo", ""),
                None,  # vendedor_id
                None,  # Distribuidor_id
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
            if cliente_id is not None and Distribuidor_id is not None:
                self.db.cursor.execute(
                    "INSERT INTO ventas (fecha, total, cliente_id, Distribuidor_id) VALUES (?, ?, ?, ?)",
                    (v.get("fecha", ""), v.get("total", 0), cliente_id, Distribuidor_id)
                )
            elif cliente_id is not None:
                self.db.cursor.execute(
                    "INSERT INTO ventas (fecha, total, cliente_id) VALUES (?, ?, ?)",
                    (v.get("fecha", ""), v.get("total", 0), cliente_id)
                )
            else:
                self.db.cursor.execute(
                    "INSERT INTO ventas (fecha, total) VALUES (?, ?)",
                    (v.get("fecha", ""), v.get("total", 0))
                )
            new_id = self.db.cursor.lastrowid
            venta_id_map[v["id"]] = new_id

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
                        d.get("vendedor_id", None)
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
        datos_path = "datos_negocio.json"
        if datos_negocio:
            with open(datos_path, "w", encoding="utf-8") as f:
                json.dump(datos_negocio, f, ensure_ascii=False, indent=2)
        elif os.path.exists(datos_path):
            # Si no hay datos del negocio en el inventario, elimina el archivo local
            os.remove(datos_path)

        # --- AGREGA DESPUÉS DE IMPORTAR VENTAS ---
        for vcf in data.get("ventas_credito_fiscal", []):
            self.db.cursor.execute("""
                INSERT INTO ventas_credito_fiscal (
                    venta_id, cliente_id, nrc, nit, giro, no_remision, orden_no, condicion_pago,
                    venta_a_cuenta_de, fecha_remision_anterior, fecha_remision,
                    sumas, iva, subtotal, total_letras,
                    ventas_exentas, ventas_no_sujetas, extra
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                venta_id_map.get(vcf.get("venta_id")),      # <-- Usa el nuevo ID de la venta
                cliente_id_map.get(vcf.get("cliente_id")),  # <-- Usa el nuevo ID del cliente
                vcf.get("nrc"),
                vcf.get("nit"),
                vcf.get("giro"),
                vcf.get("no_remision"),
                vcf.get("orden_no"),
                vcf.get("condicion_pago"),
                vcf.get("venta_a_cuenta_de"),
                vcf.get("fecha_remision_anterior"),
                vcf.get("fecha_remision"),
                vcf.get("sumas", 0),
                vcf.get("iva", 0),
                vcf.get("subtotal", 0),
                vcf.get("total_letras", ""),
                vcf.get("ventas_exentas", 0),
                vcf.get("ventas_no_sujetas", 0),
                vcf.get("extra", None)
            ))
        self.db.conn.commit()

    def add_Distribuidor(self, nombre):
        self.db.add_Distribuidor(nombre)
        self.refresh_data()

    def add_vendedor(self, nombre, Distribuidor_id=None, codigo=None):
        self.db.add_vendedor(nombre, Distribuidor_id=Distribuidor_id, codigo=codigo)
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
                return QColor("green")
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