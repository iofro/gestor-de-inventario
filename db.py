import sqlite3
from datetime import datetime
import json
import logging
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class DB:
    def __init__(self, db_name=os.path.join(os.path.dirname(__file__), "inventario.db")):
        self.conn = sqlite3.connect(db_name)
        self.conn.row_factory = sqlite3.Row
        self.cursor = self.conn.cursor()
        self.setup()

    def ensure_column(self, table: str, column: str, definition: str) -> bool:
        """Ensure that a specific column exists in ``table``.

        If the column is missing the user is asked whether it should be created.
        Returns ``True`` if the column exists or was created successfully.
        """
        self.cursor.execute(f"PRAGMA table_info({table})")
        cols = [row[1] for row in self.cursor.fetchall()]
        if column not in cols:
            resp = input(
                f"La tabla '{table}' no tiene la columna '{column}'. ¿Crear columna? (s/n): "
            )
            if resp.strip().lower().startswith("s"):
                self.cursor.execute(
                    f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
                )
                self.conn.commit()
                print(f"Columna '{column}' creada en '{table}'.")
                return True
            print(
                f"No se agregó la columna '{column}'. Algunas funciones podrían fallar."
            )
            return False
        return True

    def setup(self):
        # Create tables if they don't exist without dropping existing data
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS Distribuidores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                codigo TEXT,
                nombre TEXT NOT NULL,
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
                dui TEXT,
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
                total REAL,
                estado TEXT DEFAULT 'Pagada'
            )
        """)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS detalles_venta (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                venta_id INTEGER,
                producto_id INTEGER,
                cantidad INTEGER,
                precio_unitario REAL,
                vendedor_id INTEGER,
                FOREIGN KEY (venta_id) REFERENCES ventas(id),
                FOREIGN KEY (producto_id) REFERENCES productos(id),
                FOREIGN KEY (vendedor_id) REFERENCES vendedores(id)
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
            CREATE TABLE IF NOT EXISTS pagos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cliente_id INTEGER,
                fecha TEXT,
                monto REAL,
                FOREIGN KEY (cliente_id) REFERENCES clientes(id)
            )
        """)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS notas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                venta_id INTEGER,
                tipo TEXT,
                fecha TEXT,
                monto REAL,
                motivo TEXT,
                FOREIGN KEY (venta_id) REFERENCES ventas(id)

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
                documento_venta_a_cuenta TEXT,
                fecha_remision_anterior TEXT,
                fecha_remision TEXT,
                sumas REAL DEFAULT 0,
                descuentos REAL DEFAULT 0,
                iva REAL DEFAULT 0,
                subtotal REAL DEFAULT 0,
                ventas_exentas REAL DEFAULT 0,
                ventas_no_sujetas REAL DEFAULT 0,
                total_letras TEXT,
                extra TEXT,
                FOREIGN KEY (venta_id) REFERENCES ventas(id),
                FOREIGN KEY (cliente_id) REFERENCES clientes(id)
            )
        """)
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS facturas_pdf (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                venta_id INTEGER,
                tipo TEXT,
                ruta TEXT,
                fecha_creacion TEXT,
                FOREIGN KEY (venta_id) REFERENCES ventas(id)
            )
        """
        )
        self.ensure_column("ventas_credito_fiscal", "documento_venta_a_cuenta", "TEXT")
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS tickets_pdf (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                venta_id INTEGER,
                ruta TEXT,
                fecha_creacion TEXT,
                FOREIGN KEY (venta_id) REFERENCES ventas(id)
            )
        """
        )

        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS dte_envios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                venta_id INTEGER,
                modo TEXT,
                estado TEXT,
                sello TEXT,
                fecha_hora TEXT,
                respuesta TEXT,

                FOREIGN KEY (venta_id) REFERENCES ventas(id)
            )
        """
        )
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
            self.cursor.execute("ALTER TABLE ventas ADD COLUMN vendedor_id INTEGER")
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
            self.cursor.execute("ALTER TABLE vendedores ADD COLUMN dui TEXT")
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
        # Asegura columnas adicionales en ventas_credito_fiscal y ventas
        for stmt in [
            "ALTER TABLE ventas_credito_fiscal ADD COLUMN sumas REAL DEFAULT 0",
            "ALTER TABLE ventas_credito_fiscal ADD COLUMN iva REAL DEFAULT 0",
            "ALTER TABLE ventas_credito_fiscal ADD COLUMN subtotal REAL DEFAULT 0",
            "ALTER TABLE ventas_credito_fiscal ADD COLUMN total_letras TEXT",
            "ALTER TABLE ventas_credito_fiscal ADD COLUMN descuentos REAL DEFAULT 0",
            "ALTER TABLE ventas ADD COLUMN extra TEXT",
            "ALTER TABLE ventas ADD COLUMN estado TEXT DEFAULT 'Pagada'",
        ]:
            try:
                self.cursor.execute(stmt)
                self.conn.commit()
            except Exception:
                pass  # La columna ya existe o no se pudo crear
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
        try:
            self.cursor.execute("ALTER TABLE detalles_venta ADD COLUMN vendedor_id INTEGER")
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

        # Verifica que la columna estado exista en ventas
        self.ensure_column("ventas", "estado", "TEXT DEFAULT 'Pagada'")

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
    def add_vendedor(self, nombre, descripcion="", Distribuidor_id=None, codigo=None, dui=None):
        if codigo is None:
            codigo = self.get_next_vendedor_codigo()
        self.cursor.execute(
            "INSERT INTO vendedores (codigo, nombre, dui, descripcion, Distribuidor_id) VALUES (?, ?, ?, ?, ?)",
            (codigo, nombre, dui, descripcion, Distribuidor_id),

        )
        self.conn.commit()

    def get_vendedores(self):
        self.cursor.execute("SELECT * FROM vendedores")
        return [dict(row) for row in self.cursor.fetchall()]

    def update_vendedor(self, id, codigo, nombre, descripcion, Distribuidor_id, dui=None):
        try:
            self.cursor.execute(
                "UPDATE vendedores SET codigo=?, nombre=?, dui=?, descripcion=?, Distribuidor_id=? WHERE id=?",
                (codigo, nombre, dui, descripcion, Distribuidor_id, id),

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
    def add_venta(
        self,
        fecha,
        total,
        cliente_id=None,
        Distribuidor_id=None,
        vendedor_id=None,
        extra=None,
        estado="Pagada",
    ):
        # Asegura que la columna estado exista antes de insertar
        self.ensure_column("ventas", "estado", "TEXT DEFAULT 'Pagada'")
        extra_json = json.dumps(extra) if extra is not None else None
        columns = ["fecha", "total", "estado"]
        values = [fecha, total, estado]
        if cliente_id is not None:
            columns.append("cliente_id")
            values.append(cliente_id)
        if Distribuidor_id is not None:
            columns.append("Distribuidor_id")
            values.append(Distribuidor_id)
        if vendedor_id is not None:
            columns.append("vendedor_id")
            values.append(vendedor_id)
        if extra_json is not None:
            columns.append("extra")
            values.append(extra_json)
        placeholders = ", ".join(["?"] * len(values))
        query = f"INSERT INTO ventas ({', '.join(columns)}) VALUES ({placeholders})"
        self.cursor.execute(query, values)
        self.conn.commit()
        return self.cursor.lastrowid

    def add_venta_credito_fiscal(
        self,
        cliente_id,
        fecha,
        total,
        nrc,
        nit,
        giro,
        Distribuidor_id=None,
        vendedor_id=None,
        no_remision="",
        orden_no="",
        condicion_pago="",
        venta_a_cuenta_de="",
        documento_venta_a_cuenta="",
        fecha_remision_anterior="",
        fecha_remision="",
        sumas=0,
        descuentos=0,
        iva=0,
        subtotal=0,
        ventas_exentas=0,
        ventas_no_sujetas=0,
        total_letras="",
        extra=None,
        estado="Pagada",
    ):
        # Asegura que la columna estado exista antes de insertar
        self.ensure_column("ventas", "estado", "TEXT DEFAULT 'Pagada'")
        self.ensure_column("ventas_credito_fiscal", "documento_venta_a_cuenta", "TEXT")
        try:
            cols = ["fecha", "total", "cliente_id", "estado"]
            vals = [fecha, total, cliente_id, estado]
            if Distribuidor_id is not None:
                cols.append("Distribuidor_id")
                vals.append(Distribuidor_id)
            if vendedor_id is not None:
                cols.append("vendedor_id")
                vals.append(vendedor_id)
            placeholders = ", ".join(["?"] * len(vals))
            q = f"INSERT INTO ventas ({', '.join(cols)}) VALUES ({placeholders})"
            self.cursor.execute(q, vals)
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
                    documento_venta_a_cuenta TEXT,
                    fecha_remision_anterior TEXT,
                    fecha_remision TEXT,
                    sumas REAL DEFAULT 0,
                    descuentos REAL DEFAULT 0,
                    iva REAL DEFAULT 0,
                    subtotal REAL DEFAULT 0,
                    ventas_exentas REAL DEFAULT 0,
                    ventas_no_sujetas REAL DEFAULT 0,
                    total_letras TEXT,
                    extra TEXT,
                    FOREIGN KEY (venta_id) REFERENCES ventas(id),
                    FOREIGN KEY (cliente_id) REFERENCES clientes(id)
                )
            """)
            extra_json = json.dumps(extra) if extra else None
            self.cursor.execute("""
                INSERT INTO ventas_credito_fiscal (
                    venta_id, cliente_id, nrc, nit, giro,
                    no_remision, orden_no, condicion_pago, venta_a_cuenta_de,
                    documento_venta_a_cuenta, fecha_remision_anterior, fecha_remision,
                    sumas, descuentos, iva, subtotal, ventas_exentas, ventas_no_sujetas, total_letras, extra
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                venta_id, cliente_id, nrc, nit, giro,
                no_remision, orden_no, condicion_pago, venta_a_cuenta_de,
                documento_venta_a_cuenta, fecha_remision_anterior, fecha_remision,
                sumas, descuentos, iva, subtotal, ventas_exentas, ventas_no_sujetas, total_letras, extra_json
            ))
            self.conn.commit()
            return venta_id
        except Exception as e:
            logger.exception("Error al agregar venta a crédito fiscal: %s", e)
            self.conn.rollback()
            raise


    def get_ventas(self):
        self.cursor.execute("SELECT * FROM ventas")
        return [dict(row) for row in self.cursor.fetchall()]

    def update_venta_estado(self, venta_id, estado):
        """Actualiza el estado de una venta."""
        self.cursor.execute(
            "UPDATE ventas SET estado=? WHERE id=?",
            (estado, venta_id),
        )
        self.conn.commit()

    def get_detalles_venta(self, venta_id):
        """Return sale line items joined with product names."""
        self.cursor.execute(
            """
            SELECT detalles_venta.*, productos.nombre AS descripcion
            FROM detalles_venta
            LEFT JOIN productos ON detalles_venta.producto_id = productos.id
            WHERE detalles_venta.venta_id=?
        """,
            (venta_id,),
        )
        return [dict(row) for row in self.cursor.fetchall()]

    def get_venta_credito_fiscal(self, venta_id):
        """Return credit-fiscal record associated with a sale, if any."""
        self.cursor.execute(
            "SELECT * FROM ventas_credito_fiscal WHERE venta_id=?", (venta_id,)
        )
        row = self.cursor.fetchone()
        if row:
            data = dict(row)
            extra = data.get("extra")
            if extra:
                try:
                    data["extra"] = json.loads(extra)
                except Exception:
                    pass
            return data
        return None

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
        query = (
            f"SELECT id, fecha, total, cliente_id, vendedor_id "
            f"FROM ventas WHERE {field}=?"
        )
        params = [persona_id]
        if fecha_inicio:
            query += " AND date(fecha) >= date(?)"
            params.append(fecha_inicio)
        if fecha_fin:
            query += " AND date(fecha) <= date(?)"
            params.append(fecha_fin)
        query += " ORDER BY fecha"
        self.cursor.execute(query, params)
        facturas = [dict(row) for row in self.cursor.fetchall()]
        for f in facturas:
            f["saldo"] = f.get("total", 0)
        return facturas

    def get_estado_cuenta_vendedores(self, vendedor_id=None, fecha_inicio=None, fecha_fin=None):
        """Genera el estado de cuenta de los vendedores.

        Si ``vendedor_id`` es ``None`` se obtienen las ventas agrupadas por
        vendedor.  Cuando se especifica un ``vendedor_id`` se devuelven todas las
        ventas registradas para ese vendedor dentro del rango indicado.
        """

        if vendedor_id is None:
            query = (
                "SELECT vendedor_id, SUM(total) AS total_ventas "
                "FROM ventas WHERE vendedor_id IS NOT NULL"
            )
            params = []
            if fecha_inicio:
                query += " AND date(fecha) >= date(?)"
                params.append(fecha_inicio)
            if fecha_fin:
                query += " AND date(fecha) <= date(?)"
                params.append(fecha_fin)
            query += " GROUP BY vendedor_id ORDER BY vendedor_id"
            self.cursor.execute(query, params)
            return [dict(row) for row in self.cursor.fetchall()]

        query = "SELECT id, fecha, total FROM ventas WHERE vendedor_id=?"
        params = [vendedor_id]
        if fecha_inicio:
            query += " AND date(fecha) >= date(?)"
            params.append(fecha_inicio)
        if fecha_fin:
            query += " AND date(fecha) <= date(?)"
            params.append(fecha_fin)
        query += " ORDER BY fecha"
        self.cursor.execute(query, params)
        return [dict(row) for row in self.cursor.fetchall()]

    def get_comision_vendedores(self, fecha_inicio=None, fecha_fin=None):
        """Return total commission per vendor within an optional date range."""
        query = (
            "SELECT dv.vendedor_id, SUM(dv.comision) AS total_comision "
            "FROM detalles_venta dv "
            "JOIN ventas v ON v.id = dv.venta_id "
            "WHERE dv.vendedor_id IS NOT NULL"
        )
        params = []
        if fecha_inicio:
            query += " AND date(v.fecha) >= date(?)"
            params.append(fecha_inicio)
        if fecha_fin:
            query += " AND date(v.fecha) <= date(?)"
            params.append(fecha_fin)
        query += " GROUP BY dv.vendedor_id ORDER BY dv.vendedor_id"
        self.cursor.execute(query, params)
        return [dict(row) for row in self.cursor.fetchall()]

    def get_estado_cuenta_clientes(self, cliente_id=None, fecha_inicio=None, fecha_fin=None):
        """Genera el estado de cuenta de los clientes.

        Si ``cliente_id`` es ``None`` se obtienen las ventas agrupadas por cliente.
        Cuando se especifica un ``cliente_id`` se devuelven todas las ventas
        registradas para ese cliente dentro del rango indicado.
        """

        if cliente_id is None:
            query = (
                "SELECT cliente_id, SUM(total) AS total_compras "
                "FROM ventas WHERE cliente_id IS NOT NULL"
            )
            params = []
            if fecha_inicio:
                query += " AND date(fecha) >= date(?)"
                params.append(fecha_inicio)
            if fecha_fin:
                query += " AND date(fecha) <= date(?)"
                params.append(fecha_fin)
            query += " GROUP BY cliente_id ORDER BY cliente_id"
            self.cursor.execute(query, params)
            return [dict(row) for row in self.cursor.fetchall()]

        query = "SELECT id, fecha, total FROM ventas WHERE cliente_id=?"
        params = [cliente_id]
        if fecha_inicio:
            query += " AND date(fecha) >= date(?)"
            params.append(fecha_inicio)
        if fecha_fin:
            query += " AND date(fecha) <= date(?)"
            params.append(fecha_fin)
        query += " ORDER BY fecha"
        self.cursor.execute(query, params)
        return [dict(row) for row in self.cursor.fetchall()]

    def delete_venta(self, id):
        try:
            self.cursor.execute("DELETE FROM ventas WHERE id=?", (id,))
            self.conn.commit()
        except Exception as e:
            logger.exception("Error al eliminar venta: %s", e)

    # CRUD DETALLES_VENTA
    def add_detalle_venta(self, venta_id, producto_id, cantidad, precio_unitario, descuento=0, descuento_tipo="", iva=0, comision=0, iva_tipo="", tipo_fiscal="", extra=None, precio_con_iva=0, vendedor_id=None):
        try:
            extra_json = json.dumps(extra) if extra else None
            self.cursor.execute("""
                INSERT INTO detalles_venta (venta_id, producto_id, cantidad, precio_unitario, descuento, descuento_tipo, iva, comision, iva_tipo, tipo_fiscal, extra, precio_con_iva, vendedor_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (venta_id, producto_id, cantidad, precio_unitario, descuento, descuento_tipo, iva, comision, iva_tipo, tipo_fiscal, extra_json, precio_con_iva, vendedor_id))
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
            UPDATE clientes SET codigo=?, nombre=?, nrc=?, nit=?, dui=?, giro=?, telefono=?, email=?, direccion=?, departamento=?, municipio=? WHERE id=?
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

    def get_cliente(self, cliente_id):
        """Return a single client by id."""
        self.cursor.execute("SELECT * FROM clientes WHERE id=?", (cliente_id,))
        row = self.cursor.fetchone()
        return dict(row) if row else None

    def add_pago(self, cliente_id, monto, fecha):
        """Registra un pago aplicado a un cliente."""
        self.cursor.execute(
            "INSERT INTO pagos (cliente_id, monto, fecha) VALUES (?, ?, ?)",
            (cliente_id, monto, fecha),
        )
        self.conn.commit()

    def get_pagos_cliente(self, cliente_id, fecha_inicio=None, fecha_fin=None):
        """Obtiene los pagos de un cliente en un rango de fechas."""
        query = "SELECT fecha, monto FROM pagos WHERE cliente_id=?"
        params = [cliente_id]
        if fecha_inicio:
            query += " AND date(fecha) >= date(?)"
            params.append(fecha_inicio)
        if fecha_fin:
            query += " AND date(fecha) <= date(?)"
            params.append(fecha_fin)
        query += " ORDER BY fecha"
        self.cursor.execute(query, params)
        return [dict(row) for row in self.cursor.fetchall()]

    def add_nota(self, venta_id, tipo, fecha, monto, motivo):
        """Registra una nota de crédito o débito."""
        self.cursor.execute(
            "INSERT INTO notas (venta_id, tipo, fecha, monto, motivo) VALUES (?, ?, ?, ?, ?)",
            (venta_id, tipo, fecha, monto, motivo),
        )
        self.conn.commit()
        return self.cursor.lastrowid

    def add_factura_pdf(self, venta_id, tipo, ruta):
        """Guarda la ruta de un PDF generado para una venta."""
        # Check if a record with the same file path already exists
        self.cursor.execute(
            "SELECT id FROM facturas_pdf WHERE ruta=?",
            (ruta,),
        )
        row = self.cursor.fetchone()
        if row:
            return row["id"]

        fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.cursor.execute(
            "INSERT INTO facturas_pdf (venta_id, tipo, ruta, fecha_creacion) VALUES (?, ?, ?, ?)",
            (venta_id, tipo, ruta, fecha),
        )
        self.conn.commit()
        return self.cursor.lastrowid

    def add_ticket_pdf(self, venta_id, ruta):
        """Almacena la ruta de un ticket generado para una venta."""
        fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.cursor.execute(
            "INSERT INTO tickets_pdf (venta_id, ruta, fecha_creacion) VALUES (?, ?, ?)",
            (venta_id, ruta, fecha),
        )
        self.conn.commit()
        return self.cursor.lastrowid

    def get_ticket_pdf(self, venta_id):
        """Devuelve la ruta del ticket más reciente asociado a una venta."""
        self.cursor.execute(
            "SELECT ruta FROM tickets_pdf WHERE venta_id=? ORDER BY fecha_creacion DESC LIMIT 1",
            (venta_id,),
        )
        row = self.cursor.fetchone()
        return row["ruta"] if row else None

    def get_factura_pdf(self, venta_id):
        """Devuelve la ruta de la factura PDF más reciente de una venta."""
        self.cursor.execute(
            "SELECT ruta FROM facturas_pdf WHERE venta_id=? ORDER BY fecha_creacion DESC LIMIT 1",
            (venta_id,),
        )
        row = self.cursor.fetchone()
        return row["ruta"] if row else None

    def delete_factura_pdf(self, venta_id):
        """Elimina registros de factura PDF asociados a una venta."""
        self.cursor.execute("DELETE FROM facturas_pdf WHERE venta_id=?", (venta_id,))
        self.conn.commit()

    def delete_ticket_pdf(self, venta_id):
        """Elimina registros de tickets PDF asociados a una venta."""
        self.cursor.execute("DELETE FROM tickets_pdf WHERE venta_id=?", (venta_id,))
        self.conn.commit()

    def add_dte_pendiente(self, venta_id, dte_json, modo):
        """Registra un DTE pendiente de transmisión a Hacienda."""
        fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.cursor.execute(
            "INSERT INTO dte_pendientes (venta_id, dte_json, modo, fecha_creacion) VALUES (?, ?, ?, ?)",
            (venta_id, json.dumps(dte_json, ensure_ascii=False), modo, fecha),
        )
        self.conn.commit()
        return self.cursor.lastrowid

    def get_dte_pendientes(self):
        """Devuelve la lista de DTE pendientes de transmitir."""
        self.cursor.execute("SELECT * FROM dte_pendientes WHERE transmitido=0")
        rows = [dict(row) for row in self.cursor.fetchall()]
        for r in rows:
            try:
                r["dte_json"] = json.loads(r["dte_json"])
            except Exception:
                pass
        return rows

    def get_notas_by_venta(self, venta_id):
        """Devuelve las notas asociadas a una venta."""
        self.cursor.execute(
            "SELECT * FROM notas WHERE venta_id=? ORDER BY fecha",
            (venta_id,),
        )
        return [dict(row) for row in self.cursor.fetchall()]

    def get_estado_cuenta_cliente(self, cliente_id, fecha_inicio=None, fecha_fin=None):
        """Genera un estado de cuenta detallado para un cliente."""
        compras = self.get_estado_cuenta(
            cliente_id, "cliente", fecha_inicio, fecha_fin
        )
        total_acumulado = sum(c.get("total", 0) for c in compras)
        pagos = self.get_pagos_cliente(cliente_id, fecha_inicio, fecha_fin)
        total_pagos = sum(p.get("monto", 0) for p in pagos)
        saldo = total_acumulado - total_pagos
        return {
            "cliente_id": cliente_id,
            "total_acumulado": total_acumulado,
            "historial_compras": compras,
            "pagos_aplicados": pagos,
            "saldo": saldo,
        }

    def limpiar_productos(self):
        self.cursor.execute("DELETE FROM productos")
        self.conn.commit()

    def limpiar_vendedores(self):
        self.cursor.execute("DELETE FROM vendedores")
        self.conn.commit()

    def limpiar_Distribuidores(self):
        self.cursor.execute("DELETE FROM Distribuidores")
        self.conn.commit()

    def limpiar_ventas_credito_fiscal(self):
        self.cursor.execute("DELETE FROM ventas_credito_fiscal")
        self.conn.commit()

    def add_Distribuidor_detallado(self, data):
        self.cursor.execute("""
            INSERT INTO Distribuidores (
                codigo, nombre, telefono, email, cargo, sucursal,
                fecha_inicio, direccion, departamento, municipio,
                tipo_contrato, comisiones_especificas, metodo_pago, nit, nrc,
                cuenta_bancaria, notas
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)

        """, (
            data.get("codigo", ""),
            data.get("nombre", ""),
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
        self.ensure_column("ventas", "estado", "TEXT DEFAULT 'Pagada'")
        fecha = data.get("fecha", "")
        total = data.get("total", 0)
        cliente_id = data.get("cliente_id")
        Distribuidor_id = data.get("Distribuidor_id")
        estado = data.get("estado", "Pagada")
        cols = ["fecha", "total", "estado"]
        vals = [fecha, total, estado]
        if cliente_id is not None:
            cols.append("cliente_id")
            vals.append(cliente_id)
        if Distribuidor_id is not None:
            cols.append("Distribuidor_id")
            vals.append(Distribuidor_id)
        placeholders = ", ".join(["?"] * len(vals))
        query = f"INSERT INTO ventas ({', '.join(cols)}) VALUES ({placeholders})"
        self.cursor.execute(query, vals)
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

    def get_trabajadores(self, solo_vendedores=False, area=None, search=""):
        query = "SELECT * FROM trabajadores"
        params = []
        filtros = []
        if solo_vendedores:
            filtros.append("es_vendedor=1")
        if area:
            filtros.append("area=?")
            params.append(area)
        if search:
            filtros.append("(nombre LIKE ? OR codigo LIKE ?)")
            params.extend([f"%{search}%", f"%{search}%"])
        if filtros:
            query += " WHERE " + " AND ".join(filtros)
        self.cursor.execute(query, params)
        return [dict(row) for row in self.cursor.fetchall()]

    def get_trabajador(self, trabajador_id):
        """Return a single trabajador by id."""
        self.cursor.execute(
            "SELECT * FROM trabajadores WHERE id=?",
            (trabajador_id,),
        )
        row = self.cursor.fetchone()
        return dict(row) if row else None

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

    # --- NOTAS DE CRÉDITO Y DÉBITO ---
    def agregar_nota(self, tipo, venta_id, fecha, monto, motivo, detalles=None):
        """Registra una nota de crédito o débito asociada a una venta."""
        if tipo not in ("credito", "debito"):
            raise ValueError("tipo debe ser 'credito' o 'debito'")

        self.cursor.execute("SELECT id FROM ventas WHERE id=?", (venta_id,))
        if self.cursor.fetchone() is None:
            raise ValueError("La venta indicada no existe")

        detalles_json = json.dumps(detalles) if detalles is not None else None
        self.cursor.execute(
            """
            INSERT INTO notas (tipo, venta_id, fecha, monto, motivo, detalles)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (tipo, venta_id, fecha, monto, motivo, detalles_json),
        )
        self.conn.commit()
        return self.cursor.lastrowid

    def obtener_notas_por_venta(self, venta_id):
        """Devuelve todas las notas registradas para una venta."""
        self.cursor.execute(
            "SELECT * FROM notas WHERE venta_id=? ORDER BY fecha",
            (venta_id,),
        )
        rows = [dict(row) for row in self.cursor.fetchall()]
        for r in rows:
            if r.get("detalles"):
                try:
                    r["detalles"] = json.loads(r["detalles"])
                except Exception:
                    pass
        return rows

    def obtener_notas(self):
        """Devuelve todas las notas registradas en el sistema."""
        self.cursor.execute("SELECT * FROM notas ORDER BY fecha")
        rows = [dict(row) for row in self.cursor.fetchall()]
        for r in rows:
            if r.get("detalles"):
                try:
                    r["detalles"] = json.loads(r["detalles"])
                except Exception:
                    pass
        return rows

    def registrar_envio_dte(self, venta_id, modo, estado, sello, respuesta_json=""):
        """Guarda un registro del estado de transmisión de un DTE."""
        self.ensure_column("dte_envios", "respuesta", "TEXT")
        fecha_hora = datetime.now().isoformat()
        self.cursor.execute(
            """
            INSERT INTO dte_envios (venta_id, modo, estado, sello, fecha_hora, respuesta)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (venta_id, modo, estado, sello, fecha_hora, respuesta_json),
        )
        self.conn.commit()

    def consultar_envio_dte(self, venta_id):
        """Devuelve el JSON almacenado en ``dte_envios.respuesta``."""
        self.ensure_column("dte_envios", "respuesta", "TEXT")
        row = self.cursor.execute(
            "SELECT respuesta FROM dte_envios WHERE venta_id=? ORDER BY id DESC LIMIT 1",
            (venta_id,),
        ).fetchone()
        if not row or not row[0]:
            return {}
        try:
            return json.loads(row[0])
        except Exception:
            return {}

    def update_venta_extra(self, venta_id, extra_dict):
        """Actualiza el campo ``extra`` de la venta, fusionando los datos."""
        self.ensure_column("ventas", "extra", "TEXT")
        self.cursor.execute("SELECT extra FROM ventas WHERE id=?", (venta_id,))
        row = self.cursor.fetchone()
        current = {}
        if row and row[0]:
            try:
                current = json.loads(row[0])
            except Exception:
                current = {}
        current.update(extra_dict)
        self.cursor.execute(
            "UPDATE ventas SET extra=? WHERE id=?",
            (json.dumps(current, ensure_ascii=False), venta_id),
        )
        self.conn.commit()