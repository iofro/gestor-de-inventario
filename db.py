import sqlite3
from datetime import datetime
import json
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class DB:
    def __init__(self, db_name="inventario.db"):
        self.conn = sqlite3.connect(db_name)
        self.conn.row_factory = sqlite3.Row
        self.cursor = self.conn.cursor()
        self.setup()

    def setup(self):
        # Create tables if they don't exist without dropping existing data
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS Distribuidores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                codigo TEXT,
                nombre TEXT NOT NULL,
                dui TEXT,
                telefono TEXT,
                email TEXT,
                cargo TEXT,
                sucursal TEXT,
                fecha_inicio TEXT,
                direccion TEXT,
                departamento TEXT,
                municipio TEXT,
                tipo_contrato TEXT,
                comisiones_especificas TEXT,
                metodo_pago TEXT,
                nit TEXT,
                nrc TEXT,
                cuenta_bancaria TEXT,
                notas TEXT
            )
        """)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS vendedores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                codigo TEXT UNIQUE,
                nombre TEXT NOT NULL,
                descripcion TEXT,
                Distribuidor_id INTEGER,
                FOREIGN KEY (Distribuidor_id) REFERENCES Distribuidores(id)
            )
        """)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS productos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL,
                codigo TEXT,
                vendedor_id INTEGER,
                Distribuidor_id INTEGER,
                precio REAL,
                stock INTEGER,
                precio_compra REAL DEFAULT 0,
                -- fecha_vencimiento TEXT,  # <-- ELIMINADA
                FOREIGN KEY (vendedor_id) REFERENCES vendedores(id),
                FOREIGN KEY (Distribuidor_id) REFERENCES Distribuidores(id)
            )
        """)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS ventas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha TEXT,
                total REAL
            )
        """)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS detalles_venta (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                venta_id INTEGER,
                producto_id INTEGER,
                cantidad INTEGER,
                precio_unitario REAL,
                FOREIGN KEY (venta_id) REFERENCES ventas(id),
                FOREIGN KEY (producto_id) REFERENCES productos(id)
            )
        """)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS Distribuidor_info (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT,
                direccion TEXT,
                telefono TEXT,
                nit TEXT,
                giro TEXT,
                representante TEXT,
                email TEXT
            )
        """)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS clientes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                codigo TEXT UNIQUE,
                nombre TEXT,
                nrc TEXT,
                nit TEXT,
                dui TEXT,
                giro TEXT,
                telefono TEXT,
                email TEXT,
                direccion TEXT,
                departamento TEXT,
                municipio TEXT,
                otros TEXT
            )
        """)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS compras (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha TEXT,
                producto_id INTEGER,
                cantidad INTEGER,
                precio_unitario REAL,
                total REAL,
                Distribuidor_id INTEGER,
                comision_pct REAL DEFAULT 0,
                comision_monto REAL DEFAULT 0,
                vendedor_id INTEGER,
                FOREIGN KEY (producto_id) REFERENCES productos(id),
                FOREIGN KEY (Distribuidor_id) REFERENCES Distribuidores(id),
                FOREIGN KEY (vendedor_id) REFERENCES vendedores(id)
            )
        """)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS detalles_compra (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                compra_id INTEGER,
                producto_id INTEGER,
                cantidad INTEGER,
                precio_unitario REAL,
                FOREIGN KEY (compra_id) REFERENCES compras(id),
                FOREIGN KEY (producto_id) REFERENCES productos(id)
            )
        """)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS movimientos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha TEXT,
                tipo TEXT, -- 'entrada', 'salida', 'ajuste'
                producto_id INTEGER,
                cantidad INTEGER,
                motivo TEXT,
                usuario TEXT
            )
        """)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS trabajadores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                codigo TEXT UNIQUE,
                nombre TEXT NOT NULL,
                dui TEXT,
                nit TEXT,
                fecha_nacimiento TEXT,
                cargo TEXT,
                area TEXT,
                fecha_contratacion TEXT,
                telefono TEXT,
                email TEXT,
                direccion TEXT,
                salario_base REAL,
                comentarios TEXT,
                es_vendedor INTEGER DEFAULT 0
            )
        """)
        # Ensure the ventas_credito_fiscal table exists
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS ventas_credito_fiscal (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                venta_id INTEGER,
                cliente_id INTEGER,
                nrc TEXT,
                nit TEXT,
                giro TEXT,
                no_remision TEXT,
                orden_no TEXT,
                condicion_pago TEXT,
                venta_a_cuenta_de TEXT,
                fecha_remision_anterior TEXT,
                fecha_remision TEXT,
                FOREIGN KEY (venta_id) REFERENCES ventas(id),
                FOREIGN KEY (cliente_id) REFERENCES clientes(id)
            )
        """)
        self.conn.commit()


        # Si no hay registro, crea uno por defecto
        self.cursor.execute("SELECT COUNT(*) FROM Distribuidor_info")
        if self.cursor.fetchone()[0] == 0:
            self.cursor.execute("INSERT INTO Distribuidor_info (nombre) VALUES ('')")
            self.conn.commit()
        try:
            self.cursor.execute("ALTER TABLE productos ADD COLUMN precio_compra REAL DEFAULT 0")
            self.conn.commit()
        except Exception:
            pass  # Ya existe la columna
        try:
            self.cursor.execute("ALTER TABLE productos ADD COLUMN precio_venta_minorista REAL DEFAULT 0")
            self.conn.commit()
        except Exception:
            pass
        try:
            self.cursor.execute("ALTER TABLE productos ADD COLUMN precio_venta_mayorista REAL DEFAULT 0")
            self.conn.commit()
        except Exception:
            pass
        try:
            self.cursor.execute("ALTER TABLE productos ADD COLUMN precio_total_mayorista REAL DEFAULT 0")
            self.conn.commit()
        except Exception:
            pass
        # Asegura que la columna Distribuidor_id exista in productos
        try:
            self.cursor.execute("ALTER TABLE productos ADD COLUMN Distribuidor_id INTEGER")
            self.conn.commit()
        except Exception:
            pass  # Ya existe la columna
        # Elimina el intento de agregar fecha_vencimiento
        # try:
        #     self.cursor.execute("ALTER TABLE productos ADD COLUMN fecha_vencimiento TEXT")
        #     self.conn.commit()
        # except Exception:
        #     pass  # Ya existe la columna
        try:
            self.cursor.execute("ALTER TABLE ventas ADD COLUMN cliente_id INTEGER")
            self.conn.commit()
        except Exception:
            pass  # Ya existe la columna
        try:
            self.cursor.execute("ALTER TABLE ventas ADD COLUMN Distribuidor_id INTEGER")
            self.conn.commit()
        except Exception:
            pass  # Ya existe la columna
        try:
            self.cursor.execute("ALTER TABLE compras ADD COLUMN Distribuidor_id INTEGER")
            self.conn.commit()
        except Exception:
            pass
        try:
            self.cursor.execute("ALTER TABLE compras ADD COLUMN comision_pct REAL DEFAULT 0")
            self.conn.commit()
        except Exception:
            pass
        try:
            self.cursor.execute("ALTER TABLE compras ADD COLUMN comision_monto REAL DEFAULT 0")
            self.conn.commit()
        except Exception:
            pass
        try:
            self.cursor.execute("ALTER TABLE detalles_compra ADD COLUMN fecha_vencimiento TEXT")
            self.conn.commit()
        except Exception:
            pass  # Ya existe la columna
        # Asegura que la columna descripcion exista en vendedores
        try:
            self.cursor.execute("ALTER TABLE vendedores ADD COLUMN descripcion TEXT")
            self.conn.commit()
        except Exception:
            pass  # Ya existe la columna
        try:
            self.cursor.execute("ALTER TABLE vendedores ADD COLUMN codigo TEXT")
            self.conn.commit()
        except Exception:
            pass  # Ya existe la columna
        try:
            self.cursor.execute("ALTER TABLE vendedores ADD COLUMN Distribuidor_id INTEGER")
            self.conn.commit()
        except Exception:
            pass  # Ya existe la columna
        try:
            self.cursor.execute("ALTER TABLE trabajadores ADD COLUMN codigo TEXT")
            self.conn.commit()
        except Exception:
            pass  # Ya existe la columna
        try:
            self.cursor.execute("ALTER TABLE detalles_compra ADD COLUMN descuento REAL DEFAULT 0")
            self.conn.commit()
        except Exception:
            pass
        try:
            self.cursor.execute("ALTER TABLE detalles_compra ADD COLUMN descuento_tipo TEXT")
            self.conn.commit()
        except Exception:
            pass
        try:
            self.cursor.execute("ALTER TABLE detalles_compra ADD COLUMN iva REAL DEFAULT 0")
            self.conn.commit()
        except Exception:
            pass
        try:
            self.cursor.execute("ALTER TABLE detalles_compra ADD COLUMN iva_tipo TEXT")
            self.conn.commit()
        except Exception:
            pass
        try:
            self.cursor.execute("ALTER TABLE detalles_compra ADD COLUMN comision_pct REAL DEFAULT 0")
            self.conn.commit()
        except Exception:
            pass
        try:
            self.cursor.execute("ALTER TABLE detalles_compra ADD COLUMN comision_monto REAL DEFAULT 0")
            self.conn.commit()
        except Exception:
            pass
        try:
            self.cursor.execute("ALTER TABLE detalles_compra ADD COLUMN comision_tipo TEXT")
            self.conn.commit()
        except Exception:
            pass
        try:
            self.cursor.execute("ALTER TABLE detalles_venta ADD COLUMN descuento REAL DEFAULT 0")
            self.conn.commit()
        except Exception:
            pass
        try:
            self.cursor.execute("ALTER TABLE detalles_venta ADD COLUMN descuento_tipo TEXT")
            self.conn.commit()
        except Exception:
            pass
        try:
            self.cursor.execute("ALTER TABLE detalles_venta ADD COLUMN iva REAL DEFAULT 0")
            self.conn.commit()
        except Exception:
            pass
        try:
            self.cursor.execute("ALTER TABLE detalles_venta ADD COLUMN comision REAL DEFAULT 0")
            self.conn.commit()
        except Exception:
            pass
        try:
            self.cursor.execute("ALTER TABLE detalles_venta ADD COLUMN iva_tipo TEXT")
            self.conn.commit()
        except Exception:
            pass
        try:
            self.cursor.execute("ALTER TABLE detalles_venta ADD COLUMN tipo_fiscal TEXT")
            self.conn.commit()
        except Exception:
            pass  # Ya existe la columna
        try:
            self.cursor.execute("ALTER TABLE ventas_credito_fiscal ADD COLUMN sumas REAL DEFAULT 0")
            self.cursor.execute("ALTER TABLE ventas_credito_fiscal ADD COLUMN iva REAL DEFAULT 0")
            self.cursor.execute("ALTER TABLE ventas_credito_fiscal ADD COLUMN subtotal REAL DEFAULT 0")
            self.cursor.execute("ALTER TABLE ventas_credito_fiscal ADD COLUMN iva_retenido REAL DEFAULT 0")
            self.cursor.execute("ALTER TABLE ventas_credito_fiscal ADD COLUMN total_letras TEXT")
            self.cursor.execute("ALTER TABLE ventas ADD COLUMN extra TEXT")
            self.conn.commit()
        except Exception:
            pass  # Ya existen
        try:
            self.cursor.execute("ALTER TABLE detalles_venta ADD COLUMN extra TEXT")
            self.conn.commit()
        except Exception:
            pass  # Ya existe la columna
        try:
            self.cursor.execute("ALTER TABLE ventas_credito_fiscal ADD COLUMN extra TEXT")
            self.conn.commit()
        except Exception:
            pass  # Ya existe la columna
        # Forzar la creación de columnas ventas_exentas y ventas_no_sujetas en ventas_credito_fiscal
        try:
            self.cursor.execute("ALTER TABLE ventas_credito_fiscal ADD COLUMN ventas_exentas REAL DEFAULT 0")
        except Exception:
            pass  # Ya existe la columna
        try:
            self.cursor.execute("ALTER TABLE ventas_credito_fiscal ADD COLUMN ventas_no_sujetas REAL DEFAULT 0")
        except Exception:
            pass  # Ya existe la columna
        try:
            self.cursor.execute("ALTER TABLE detalles_venta ADD COLUMN precio_con_iva REAL DEFAULT 0")
            self.conn.commit()
        except Exception:
            pass  # Ya existe la columna
        # Índices únicos para códigos de clientes y vendedores
        self.cursor.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_clientes_codigo ON clientes(codigo)"
        )
        self.cursor.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_vendedores_codigo ON vendedores(codigo)"
        )
        self.cursor.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_trabajadores_codigo ON trabajadores(codigo)"
        )
        self.conn.commit()

    # CRUD Distribuidores
    def add_Distribuidor(self, nombre):
        self.cursor.execute("INSERT INTO Distribuidores (nombre) VALUES (?)", (nombre,))
        self.conn.commit()

    def get_Distribuidores(self):
        self.cursor.execute("SELECT * FROM Distribuidores")
        return [dict(row) for row in self.cursor.fetchall()]

    def update_Distribuidor(self, id, nombre):
        try:
            self.cursor.execute("UPDATE Distribuidores SET nombre=? WHERE id=?", (nombre, id))
            self.conn.commit()
        except Exception as e:
            logger.exception("Error al actualizar Distribuidor: %s", e)

    def delete_Distribuidor(self, id):
        try:
            self.cursor.execute("DELETE FROM Distribuidores WHERE id=?", (id,))
            self.conn.commit()
        except Exception as e:
            logger.exception("Error al eliminar Distribuidor: %s", e)

    # CRUD VENDEDORES (antes vendedores)
    def add_vendedor(self, nombre, descripcion="", Distribuidor_id=None, codigo=None):
        if codigo is None:
            codigo = self.get_next_vendedor_codigo()
        self.cursor.execute(
            "INSERT INTO vendedores (codigo, nombre, descripcion, Distribuidor_id) VALUES (?, ?, ?, ?)",
            (codigo, nombre, descripcion, Distribuidor_id),
        )
        self.conn.commit()

    def get_vendedores(self):
        self.cursor.execute("SELECT * FROM vendedores")
        return [dict(row) for row in self.cursor.fetchall()]

    def update_vendedor(self, id, codigo, nombre, descripcion, Distribuidor_id):
        try:
            self.cursor.execute(
                "UPDATE vendedores SET codigo=?, nombre=?, descripcion=?, Distribuidor_id=? WHERE id=?",
                (codigo, nombre, descripcion, Distribuidor_id, id),
            )
            self.conn.commit()
        except Exception as e:
            logger.exception("Error al actualizar vendedor: %s", e)

    def delete_vendedor(self, id):
        try:
            self.cursor.execute("DELETE FROM vendedores WHERE id=?", (id,))
            self.conn.commit()
        except Exception as e:
            logger.exception("Error al eliminar vendedor: %s", e)

    # CRUD PRODUCTOS
    def add_producto(self, nombre, codigo, vendedor_id, Distribuidor_id, precio_compra, precio_venta_minorista, precio_venta_mayorista, stock):
        # Elimina fecha_vencimiento del método y de la consulta
        self.cursor.execute(
            "INSERT INTO productos (nombre, codigo, vendedor_id, Distribuidor_id, precio_compra, precio_venta_minorista, precio_venta_mayorista, stock) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (nombre, codigo, vendedor_id, Distribuidor_id, precio_compra, precio_venta_minorista, precio_venta_mayorista, stock)
        )
        self.conn.commit()

    def get_productos(self, vendedor_id=None, Distribuidor_id=None, search=""):
        query = "SELECT * FROM productos"
        params = []
        filtros = []
        if vendedor_id:
            filtros.append("vendedor_id=?")
            params.append(vendedor_id)
        if Distribuidor_id:
            filtros.append("Distribuidor_id=?")
            params.append(Distribuidor_id)
        if search:
            filtros.append("(nombre LIKE ? OR codigo LIKE ?)")
            params.extend([f"%{search}%", f"%{search}%"])
        if filtros:
            query += " WHERE " + " AND ".join(filtros)
        self.cursor.execute(query, params)
        return [dict(row) for row in self.cursor.fetchall()]

    def edit_producto(self, producto_id, nombre, codigo, vendedor_id, Distribuidor_id, precio_compra, precio_venta_minorista, precio_venta_mayorista, stock):
        # Elimina fecha_vencimiento del método y de la consulta
        self.cursor.execute(
            "UPDATE productos SET nombre=?, codigo=?, vendedor_id=?, Distribuidor_id=?, precio_compra=?, precio_venta_minorista=?, precio_venta_mayorista=?, stock=? WHERE id=?",
            (nombre, codigo, vendedor_id, Distribuidor_id, precio_compra, precio_venta_minorista, precio_venta_mayorista, stock, producto_id)
        )
        self.conn.commit()

    def delete_producto(self, producto_id):
        self.cursor.execute("DELETE FROM productos WHERE id=?", (producto_id,))
        self.conn.commit()

    # CRUD VENTAS
    def add_venta(self, fecha, total, cliente_id=None, Distribuidor_id=None, vendedor_id=None, extra=None):
        extra_json = json.dumps(extra) if extra else None
        if cliente_id is not None and Distribuidor_id is not None and vendedor_id is not None:
            self.cursor.execute(
                "INSERT INTO ventas (fecha, total, cliente_id, Distribuidor_id, vendedor_id, extra) VALUES (?, ?, ?, ?, ?, ?)",
                (fecha, total, cliente_id, Distribuidor_id, vendedor_id, extra)
            )
        elif cliente_id is not None and Distribuidor_id is not None:
            self.cursor.execute(
                "INSERT INTO ventas (fecha, total, cliente_id, Distribuidor_id) VALUES (?, ?, ?, ?)",
                (fecha, total, cliente_id, Distribuidor_id)
            )
        elif cliente_id is not None:
            self.cursor.execute(
                "INSERT INTO ventas (fecha, total, cliente_id, vendedor_id) VALUES (?, ?, ?, ?)",
                (fecha, total, cliente_id, vendedor_id)
            )
        elif Distribuidor_id is not None:
            self.cursor.execute(
                "INSERT INTO ventas (fecha, total, Distribuidor_id, vendedor_id) VALUES (?, ?, ?, ?)",
                (fecha, total, Distribuidor_id, vendedor_id)
            )
        elif vendedor_id is not None:
            self.cursor.execute(
                "INSERT INTO ventas (fecha, total, vendedor_id) VALUES (?, ?, ?)",
                (fecha, total, vendedor_id)
            )
        else:
            self.cursor.execute(
                "INSERT INTO ventas (fecha, total) VALUES (?, ?)",
                (fecha, total)
            )
        self.conn.commit()
        return self.cursor.lastrowid

    def add_venta_credito_fiscal(self, cliente_id, fecha, total, nrc, nit, giro, Distribuidor_id=None, vendedor_id=None,
                                 no_remision="", orden_no="", condicion_pago="", venta_a_cuenta_de="",
                                 fecha_remision_anterior="", fecha_remision="",
                                 sumas=0, iva=0, subtotal=0, iva_retenido=0,
                                 ventas_exentas=0, ventas_no_sujetas=0,   # <-- AGREGA ESTOS
                                 total_letras="", extra=None):
        try:
            if Distribuidor_id is not None and vendedor_id is not None:
                self.cursor.execute(
                    "INSERT INTO ventas (fecha, total, cliente_id, Distribuidor_id, vendedor_id) VALUES (?, ?, ?, ?, ?)",
                    (fecha, total, cliente_id, Distribuidor_id, vendedor_id)
                )
            elif Distribuidor_id is not None:
                self.cursor.execute(
                    "INSERT INTO ventas (fecha, total, cliente_id, Distribuidor_id) VALUES (?, ?, ?, ?)",
                    (fecha, total, cliente_id, Distribuidor_id)
                )
            elif vendedor_id is not None:
                self.cursor.execute(
                    "INSERT INTO ventas (fecha, total, cliente_id, vendedor_id) VALUES (?, ?, ?, ?)",
                    (fecha, total, cliente_id, vendedor_id)
                )
            else:
                self.cursor.execute(
                    "INSERT INTO ventas (fecha, total, cliente_id) VALUES (?, ?, ?)",
                    (fecha, total, cliente_id)
                )
            venta_id = self.cursor.lastrowid
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS ventas_credito_fiscal (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    venta_id INTEGER,
                    cliente_id INTEGER,
                    nrc TEXT,
                    nit TEXT,
                    giro TEXT,
                    no_remision TEXT,
                    orden_no TEXT,
                    condicion_pago TEXT,
                    venta_a_cuenta_de TEXT,
                    fecha_remision_anterior TEXT,
                    fecha_remision TEXT,
                    FOREIGN KEY (venta_id) REFERENCES ventas(id),
                    FOREIGN KEY (cliente_id) REFERENCES clientes(id)
                )
            """)
            extra_json = json.dumps(extra) if extra else None
            self.cursor.execute("""
                INSERT INTO ventas_credito_fiscal (
                    venta_id, cliente_id, nrc, nit, giro,
                    no_remision, orden_no, condicion_pago, venta_a_cuenta_de,
                    fecha_remision_anterior, fecha_remision,
                    sumas, iva, subtotal, iva_retenido, ventas_exentas, ventas_no_sujetas, total_letras, extra
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                venta_id, cliente_id, nrc, nit, giro,
                no_remision, orden_no, condicion_pago, venta_a_cuenta_de,
                fecha_remision_anterior, fecha_remision,
                sumas, iva, subtotal, iva_retenido, ventas_exentas, ventas_no_sujetas, total_letras, extra_json
            ))
            self.conn.commit()
            return venta_id
        except Exception as e:
            logger.exception("Error al agregar venta a crédito fiscal: %s", e)
            return None

    def get_ventas(self):
        self.cursor.execute("SELECT * FROM ventas")
        return [dict(row) for row in self.cursor.fetchall()]

    def get_detalles_venta(self, venta_id):
        self.cursor.execute("SELECT * FROM detalles_venta WHERE venta_id=?", (venta_id,))
        return [dict(row) for row in self.cursor.fetchall()]

    def get_compras(self):
        self.cursor.execute("SELECT * FROM compras")
        return [dict(row) for row in self.cursor.fetchall()]

    def get_detalles_compra(self, compra_id):
        self.cursor.execute("SELECT * FROM detalles_compra WHERE compra_id=?", (compra_id,))
        return [dict(row) for row in self.cursor.fetchall()]

    def get_estado_cuenta(self, persona_id, tipo="cliente", fecha_inicio=None, fecha_fin=None):
        """Obtiene las facturas de un cliente o vendedor en un rango de fechas.

        Si ``fecha_inicio`` y ``fecha_fin`` son ``None``, se devuelven todas las
        facturas. Para filtrar el "año en curso" se puede pasar ``fecha_inicio``
        como el 1 de enero del año actual y ``fecha_fin`` como la fecha actual.
        """
        if tipo not in ("cliente", "vendedor"):
            raise ValueError("tipo debe ser 'cliente' o 'vendedor'")

        field = "cliente_id" if tipo == "cliente" else "vendedor_id"
        query = f"SELECT id, fecha, total FROM ventas WHERE {field}=?"
        params = [persona_id]
        if fecha_inicio:
            query += " AND fecha >= ?"
            params.append(fecha_inicio)
        if fecha_fin:
            query += " AND fecha <= ?"
            params.append(fecha_fin)
        query += " ORDER BY fecha"
        self.cursor.execute(query, params)
        facturas = [dict(row) for row in self.cursor.fetchall()]
        for f in facturas:
            f["saldo"] = f.get("total", 0)
        return facturas

    def delete_venta(self, id):
        try:
            self.cursor.execute("DELETE FROM ventas WHERE id=?", (id,))
            self.conn.commit()
        except Exception as e:
            logger.exception("Error al eliminar venta: %s", e)

    # CRUD DETALLES_VENTA
    def add_detalle_venta(self, venta_id, producto_id, cantidad, precio_unitario, descuento=0, descuento_tipo="", iva=0, comision=0, iva_tipo="", tipo_fiscal="", extra=None, precio_con_iva=0):
        try:
            extra_json = json.dumps(extra) if extra else None
            self.cursor.execute("""
                INSERT INTO detalles_venta (venta_id, producto_id, cantidad, precio_unitario, descuento, descuento_tipo, iva, comision, iva_tipo, tipo_fiscal, extra, precio_con_iva)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (venta_id, producto_id, cantidad, precio_unitario, descuento, descuento_tipo, iva, comision, iva_tipo, tipo_fiscal, extra_json, precio_con_iva))
            self.conn.commit()
        except Exception as e:
            logger.exception("Error al agregar detalle de venta: %s", e)

    def delete_detalle_venta(self, id):
        try:
            self.cursor.execute("DELETE FROM detalles_venta WHERE id=?", (id,))
            self.conn.commit()
        except Exception as e:
            logger.exception("Error al eliminar detalle de venta: %s", e)

    def aumentar_stock(self, producto_id, cantidad):
        self.cursor.execute("UPDATE productos SET stock = stock + ? WHERE id = ?", (cantidad, producto_id))
        self.conn.commit()

    def close(self):
        self.conn.close()

    def get_Distribuidor_info(self):
        self.cursor.execute("SELECT * FROM Distribuidor_info LIMIT 1")
        return self.cursor.fetchone()

    def update_Distribuidor_info(self, nombre, direccion, telefono, nit, giro, representante, email):
        self.cursor.execute("""
            UPDATE Distribuidor_info SET
                nombre=?, direccion=?, telefono=?, nit=?, giro=?, representante=?, email=?
            WHERE id=1
        """, (nombre, direccion, telefono, nit, giro, representante, email))
        self.conn.commit()

    def get_Distribuidor_names(self):
        self.cursor.execute("SELECT nombre FROM Distribuidores")
        return [row["nombre"] for row in self.cursor.fetchall()]

    # CRUD CLIENTES
    def add_cliente(self, nombre, nrc, nit, dui, giro, telefono, email, direccion, departamento, municipio, codigo=None):
        if codigo is None:
            codigo = self.get_next_cliente_codigo()
        self.cursor.execute(
            """
            INSERT INTO clientes (codigo, nombre, nrc, nit, dui, giro, telefono, email, direccion, departamento, municipio)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (codigo, nombre, nrc, nit, dui, giro, telefono, email, direccion, departamento, municipio),
        )
        self.conn.commit()

    def get_next_cliente_codigo(self):
        self.cursor.execute("SELECT MAX(id) FROM clientes")
        max_id = self.cursor.fetchone()[0]
        return f"C-{(max_id + 1) if max_id else 1:03d}"

    def get_next_vendedor_codigo(self):
        self.cursor.execute("SELECT MAX(id) FROM vendedores")
        max_id = self.cursor.fetchone()[0]
        return f"V-{(max_id + 1) if max_id else 1:03d}"

    def get_next_trabajador_codigo(self):
        self.cursor.execute("SELECT MAX(id) FROM trabajadores")
        max_id = self.cursor.fetchone()[0]
        return f"T-{(max_id + 1) if max_id else 1:03d}"

    def update_cliente(self, id, codigo, nombre, nrc, nit, dui, giro, telefono, email, direccion, departamento, municipio):
        self.cursor.execute(
            """
            UPDATE clientes SET codigo=?, nombre=?, nrc=?, nit=?, dui=?, giro=?, telefono=?, email=?, direccion=?, departamento=?, municipio=?
            WHERE id=?
            """,
            (
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
                id,
            ),
        )
        self.conn.commit()

    def delete_cliente(self, id):
        self.cursor.execute("DELETE FROM clientes WHERE id=?", (id,))
        self.conn.commit()

    def get_clientes(self, search=""):
        query = "SELECT * FROM clientes"
        params = []
        if search:
            query += " WHERE nombre LIKE ? OR codigo LIKE ? OR nit LIKE ?"
            params = [f"%{search}%"] * 3
        self.cursor.execute(query, params)
        return [dict(row) for row in self.cursor.fetchall()]

    def limpiar_productos(self):
        self.cursor.execute("DELETE FROM productos")
        self.conn.commit()

    def limpiar_vendedores(self):
        self.cursor.execute("DELETE FROM vendedores")
        self.conn.commit()

    def limpiar_Distribuidores(self):
        self.cursor.execute("DELETE FROM Distribuidores")
        self.conn.commit()

    def add_Distribuidor_detallado(self, data):
        self.cursor.execute("""
            INSERT INTO Distribuidores (
                codigo, nombre, dui, telefono, email, cargo, sucursal,
                fecha_inicio, direccion, departamento, municipio,
                tipo_contrato, comisiones_especificas, metodo_pago, nit, nrc,
                cuenta_bancaria, notas
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            data.get("codigo", ""),
            data.get("nombre", ""),
            data.get("dui", ""),
            data.get("telefono", ""),
            data.get("email", ""),
            data.get("cargo", ""),
            data.get("sucursal", ""),
            data.get("fecha_inicio", ""),
            data.get("direccion", ""),
            data.get("departamento", ""),
            data.get("municipio", ""),
            data.get("tipo_contrato", ""),
            data.get("comisiones_especificas", ""),
            data.get("metodo_pago", ""),
            data.get("nit", ""),
            data.get("nrc", ""),
            data.get("cuenta_bancaria", ""),
            data.get("notas", "")
        ))
        self.conn.commit()

    def add_compra_detallada(self, data):
        self.cursor.execute("""
            INSERT INTO compras (fecha, producto_id, cantidad, precio_unitario, total, Distribuidor_id, comision_pct, comision_monto, vendedor_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            data.get("fecha", ""),
            data.get("producto_id", None),
            data.get("cantidad", 0),
            data.get("precio_unitario", 0),
            data.get("total", 0),
            data.get("Distribuidor_id", None),
            data.get("comision_pct", 0),
            data.get("comision_monto", 0),
            data.get("vendedor_id", None)
        ))
        self.conn.commit()
        return self.cursor.lastrowid  # <-- RETORNA EL ID

    def add_detalle_compra(self, compra_id, producto_id, cantidad, precio_unitario, fecha_vencimiento="",
                           descuento=0, descuento_tipo="", iva=0, iva_tipo="", comision_pct=0, comision_monto=0, comision_tipo=""):
        self.cursor.execute("""
            INSERT INTO detalles_compra (
                compra_id, producto_id, cantidad, precio_unitario, fecha_vencimiento,
                descuento, descuento_tipo, iva, iva_tipo, comision_pct, comision_monto, comision_tipo
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            compra_id, producto_id, cantidad, precio_unitario, fecha_vencimiento,
            descuento, descuento_tipo, iva, iva_tipo, comision_pct, comision_monto, comision_tipo
        ))
        self.conn.commit()


    def add_movimiento(self, fecha, tipo, producto_id, cantidad, motivo="", usuario=""):
        self.cursor.execute("""
            INSERT INTO movimientos (fecha, tipo, producto_id, cantidad, motivo, usuario)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (fecha, tipo, producto_id, cantidad, motivo, usuario))
        self.conn.commit()

    def get_movimientos(self):
        self.cursor.execute("SELECT * FROM movimientos")
        return [dict(row) for row in self.cursor.fetchall()]

    def add_venta_detallada(self, data):
        # data es un dict con los campos de la tabla ventas
        # Inserta la venta principal
        fecha = data.get("fecha", "")
        total = data.get("total", 0)
        cliente_id = data.get("cliente_id", None)
        Distribuidor_id = data.get("Distribuidor_id", None)
        if cliente_id is not None and Distribuidor_id is not None:
            self.cursor.execute(
                "INSERT INTO ventas (fecha, total, cliente_id, Distribuidor_id) VALUES (?, ?, ?, ?)",
                (fecha, total, cliente_id, Distribuidor_id)
            )
        elif cliente_id is not None:
            self.cursor.execute(
                "INSERT INTO ventas (fecha, total, cliente_id, Distribuidor_id) VALUES (?, ?, ?, ?)",
                (fecha, total, cliente_id, None)
            )
        elif Distribuidor_id is not None:
            self.cursor.execute(
                "INSERT INTO ventas (fecha, total, cliente_id, Distribuidor_id) VALUES (?, ?, ?, ?)",
                (fecha, total, None, Distribuidor_id)
            )
        else:
            self.cursor.execute(
                "INSERT INTO ventas (fecha, total) VALUES (?, ?)",
                (fecha, total)
            )
        venta_id = self.cursor.lastrowid

        # Si hay detalles de venta en el dict, agrégalos
        detalles = data.get("detalles", [])
        for d in detalles:
            self.cursor.execute("""
                INSERT INTO detalles_venta (venta_id, producto_id, cantidad, precio_unitario)
                VALUES (?, ?, ?, ?)
            """, (
                venta_id,
                d.get("producto_id"),
                d.get("cantidad"),
                d.get("precio_unitario")
            ))
        self.conn.commit()

    def add_trabajador(self, data):
        codigo = data.get("codigo") or self.get_next_trabajador_codigo()
        self.cursor.execute(
            """
            INSERT INTO trabajadores (codigo, nombre, dui, nit, fecha_nacimiento, cargo, area, fecha_contratacion,
                telefono, email, direccion, salario_base, comentarios, es_vendedor)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                codigo,
                data.get("nombre", ""),
                data.get("dui", ""),
                data.get("nit", ""),
                data.get("fecha_nacimiento", ""),
                data.get("cargo", ""),
                data.get("area", ""),
                data.get("fecha_contratacion", ""),
                data.get("telefono", ""),
                data.get("email", ""),
                data.get("direccion", ""),
                data.get("salario_base", None),
                data.get("comentarios", ""),
                1 if data.get("es_vendedor") else 0,
            ),
        )
        self.conn.commit()

    def get_trabajadores(self, solo_vendedores=False, area=None):
        query = "SELECT * FROM trabajadores"
        params = []
        filtros = []
        if solo_vendedores:
            filtros.append("es_vendedor=1")
        if area:
            filtros.append("area=?")
            params.append(area)
        if filtros:
            query += " WHERE " + " AND ".join(filtros)
        self.cursor.execute(query, params)
        return [dict(row) for row in self.cursor.fetchall()]

    def update_trabajador(self, id, data):
        self.cursor.execute(
            """
            UPDATE trabajadores SET
                codigo=?, nombre=?, dui=?, nit=?, fecha_nacimiento=?, cargo=?, area=?, fecha_contratacion=?,
                telefono=?, email=?, direccion=?, salario_base=?, comentarios=?, es_vendedor=?
            WHERE id=?
        """,
            (
                data.get("codigo", ""),
                data.get("nombre", ""),
                data.get("dui", ""),
                data.get("nit", ""),
                data.get("fecha_nacimiento", ""),
                data.get("cargo", ""),
                data.get("area", ""),
                data.get("fecha_contratacion", ""),
                data.get("telefono", ""),
                data.get("email", ""),
                data.get("direccion", ""),
                data.get("salario_base", None),
                data.get("comentarios", ""),
                1 if data.get("es_vendedor") else 0,
                id,
            ),
        )
        self.conn.commit()

    def delete_trabajador(self, id):
        self.cursor.execute("DELETE FROM trabajadores WHERE id=?", (id,))
        self.conn.commit()

    def disminuir_stock_lote(self, lote_id, cantidad):
        """Disminuye el stock del lote (detalle de compra) correspondiente."""
        self.cursor.execute(
            "UPDATE detalles_compra SET cantidad = cantidad - ? WHERE id = ?",
            (cantidad, lote_id)
        )
        self.conn.commit()

    def actualizar_stock_producto(self, producto_id):
        self.cursor.execute(
            "SELECT SUM(cantidad) FROM detalles_compra WHERE producto_id=?",
            (producto_id,)
        )
        total = self.cursor.fetchone()[0] or 0
        self.cursor.execute(
            "UPDATE productos SET stock=? WHERE id=?",
            (total, producto_id)
        )
        self.conn.commit()