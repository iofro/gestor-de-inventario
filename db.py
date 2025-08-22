import sqlite3
from datetime import datetime
import json
import logging
import threading
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class DB:
    def __init__(self, db_name: str | Path | None = None):
        if db_name is None:
            db_path = Path.home() / ".gestor-inventario" / "inventario.db"
        else:
            db_path = Path(db_name)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        # ``check_same_thread=False`` allows the connection to be used from
        # multiple threads.  Each thread should ideally use its own connection
        # but this flag prevents SQLite from raising an exception if a
        # connection crosses thread boundaries.
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.row_factory = sqlite3.Row
        self.cursor = self.conn.cursor()
        # Simple mutex to guard database operations when the same connection is
        # accessed from multiple threads.  Threads may also create their own
        # ``DB`` instances to keep connections separate.
        self.lock = threading.Lock()
        self.setup()

    def ensure_column(self, table: str, column: str, definition: str) -> bool:
        """Ensure that a specific column exists in ``table``.

        Missing columns are created automatically. If the creation fails a
        warning is logged. Returns ``True`` if the column exists or was created
        successfully, ``False`` otherwise.
        """
        self.cursor.execute(f"PRAGMA table_info({table})")
        cols = [row[1] for row in self.cursor.fetchall()]
        if column not in cols:
            try:
                self.cursor.execute(
                    f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
                )
                self.conn.commit()
                logger.info("Column '%s' added to '%s'.", column, table)
                return True
            except Exception as exc:  # sqlite3.OperationalError, etc.
                logger.warning(
                    "No se agregó la columna '%s' en '%s': %s", column, table, exc
                )
                return False
        return True

    def add_column_if_missing(self, table: str, column_def: str) -> bool:
        """Add a column to ``table`` if it is missing.

        ``column_def`` should include the column name and its definition
        (e.g. ``"nombre TEXT"``). Returns ``True`` if the column exists or
        was created successfully, otherwise ``False``. Failures are logged
        using ``logger``.
        """
        column = column_def.split()[0]
        self.cursor.execute(f"PRAGMA table_info({table})")
        cols = [row[1] for row in self.cursor.fetchall()]
        if column in cols:
            return True
        try:
            self.cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column_def}")
            self.conn.commit()
            return True
        except Exception:
            logger.exception("Failed to add column %s to table %s", column, table)
            return False

    def _ensure_default_users(self) -> None:
        """Create default user, admin and guest accounts if missing."""
        users = [
            ("invitado", "", "guest"),
            ("usuario", "usuario", "user"),
            ("admin", "admin", "admin"),
        ]
        for username, password, role in users:
            self.cursor.execute(
                "SELECT id FROM usuarios WHERE username=?", (username,)
            )
            if not self.cursor.fetchone():
                self.cursor.execute(
                    "INSERT INTO usuarios (username, password, role) VALUES (?, ?, ?)",
                    (username, password, role),
                )
        self.conn.commit()

    def migrate_ventas_cliente_fk(self):
        """Ensure ``ventas`` has proper foreign keys for cliente and vendedor.

        Older database versions created ``ventas`` without the cliente foreign
        key or pointing ``vendedor_id`` to the ``vendedores`` table.  SQLite
        does not support adding or altering foreign keys via ``ALTER TABLE``,
        so we migrate by recreating the table when constraints are missing or
        incorrect.
        """
        self.cursor.execute("PRAGMA foreign_key_list(ventas)")
        fk_data = self.cursor.fetchall()
        fk_cliente = any(
            row[2] == "clientes" and row[3] == "cliente_id" for row in fk_data
        )
        fk_vendedor = any(
            row[2] == "trabajadores" and row[3] == "vendedor_id" for row in fk_data
        )
        if fk_cliente and fk_vendedor:
            # Index might be missing in some installations
            self.cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_ventas_cliente_id ON ventas(cliente_id)"
            )
            return
        logger.info("Migrating 'ventas' table to fix foreign keys")
        self.cursor.execute("PRAGMA foreign_keys=off")
        try:
            self.cursor.execute(
                """
                CREATE TABLE ventas_temp (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fecha TEXT,
                    total REAL,
                    estado TEXT DEFAULT 'Pagada',
                    cliente_id INTEGER,
                    Distribuidor_id INTEGER,
                    vendedor_id INTEGER,
                    extra TEXT,
                    sincronizada BOOLEAN DEFAULT 0,
                FOREIGN KEY (cliente_id) REFERENCES clientes(id),
                FOREIGN KEY (Distribuidor_id) REFERENCES Distribuidores(id) ON DELETE RESTRICT,
                FOREIGN KEY (vendedor_id) REFERENCES trabajadores(id) ON DELETE RESTRICT
            )
        """
            )
            self.cursor.execute(
                """
                INSERT INTO ventas_temp (id, fecha, total, estado, cliente_id, Distribuidor_id, vendedor_id, extra, sincronizada)
                SELECT id, fecha, total, estado, cliente_id, Distribuidor_id, vendedor_id, extra, sincronizada FROM ventas
                """
            )
            self.cursor.execute("DROP TABLE ventas")
            self.cursor.execute("ALTER TABLE ventas_temp RENAME TO ventas")
            self.cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_ventas_cliente_id ON ventas(cliente_id)"
            )
            self.conn.commit()
        finally:
            self.cursor.execute("PRAGMA foreign_keys=on")

    def migrate_detalles_venta_vendedor_fk(self):
        """Ensure ``detalles_venta`` references ``trabajadores`` via ``vendedor_id``."""
        self.cursor.execute("PRAGMA foreign_key_list(detalles_venta)")
        fk_exists = any(
            row[2] == "trabajadores" and row[3] == "vendedor_id"
            for row in self.cursor.fetchall()
        )
        if fk_exists:
            return
        logger.info("Migrating 'detalles_venta' table to reference trabajadores")
        self.cursor.execute("PRAGMA foreign_keys=off")
        try:
            self.cursor.execute(
                """
                CREATE TABLE detalles_venta_temp (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    venta_id INTEGER,
                    producto_id INTEGER,
                    cantidad INTEGER,
                    precio_unitario REAL,
                    descuento REAL DEFAULT 0,
                    descuento_tipo TEXT,
                    iva REAL DEFAULT 0,
                    comision REAL DEFAULT 0,
                    iva_tipo TEXT,
                    tipo_fiscal TEXT,
                    extra TEXT,
                    precio_con_iva REAL DEFAULT 0,
                    vendedor_id INTEGER,
                    FOREIGN KEY (venta_id) REFERENCES ventas(id),
                    FOREIGN KEY (producto_id) REFERENCES productos(id),
                    FOREIGN KEY (vendedor_id) REFERENCES trabajadores(id) ON DELETE SET NULL
                )
                """
            )
            self.cursor.execute(
                """
                INSERT INTO detalles_venta_temp (
                    id, venta_id, producto_id, cantidad, precio_unitario,
                    descuento, descuento_tipo, iva, comision, iva_tipo,
                    tipo_fiscal, extra, precio_con_iva, vendedor_id
                )
                SELECT id, venta_id, producto_id, cantidad, precio_unitario,
                       descuento, descuento_tipo, iva, comision, iva_tipo,
                       tipo_fiscal, extra, precio_con_iva, vendedor_id
                FROM detalles_venta
                """
            )
            self.cursor.execute("DROP TABLE detalles_venta")
            self.cursor.execute("ALTER TABLE detalles_venta_temp RENAME TO detalles_venta")
            self.conn.commit()
        finally:
            self.cursor.execute("PRAGMA foreign_keys=on")

    def ensure_vendedores_trabajadores(self):
        """Ensure every vendedor has a corresponding trabajador entry."""
        self.cursor.execute("SELECT id, codigo, nombre, dui FROM vendedores")
        for vend in self.cursor.fetchall():
            self.cursor.execute(
                "SELECT 1 FROM trabajadores WHERE id=?", (vend["id"],)
            )
            if self.cursor.fetchone():
                continue
            self.cursor.execute(
                """
                INSERT INTO trabajadores (id, codigo, nombre, dui, es_vendedor)
                VALUES (?, ?, ?, ?, 1)
                """,
                (vend["id"], vend["codigo"], vend["nombre"], vend["dui"]),
            )
        self.conn.commit()

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
                FOREIGN KEY (Distribuidor_id) REFERENCES Distribuidores(id) ON DELETE SET NULL
            )
        """)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS productos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL,
                codigo TEXT,
                sku TEXT,
                vendedor_id INTEGER,
                Distribuidor_id INTEGER,
                precio REAL,
                stock INTEGER,
                precio_compra REAL DEFAULT 0,
                -- fecha_vencimiento TEXT,  # <-- ELIMINADA
                FOREIGN KEY (vendedor_id) REFERENCES vendedores(id) ON DELETE SET NULL,
                FOREIGN KEY (Distribuidor_id) REFERENCES Distribuidores(id) ON DELETE SET NULL
            )
        """)
        self.cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_productos_vendedor_id ON productos(vendedor_id)"
        )
        self.cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_productos_distribuidor_id ON productos(Distribuidor_id)"
        )
        self.cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_productos_codigo ON productos(codigo)"
        )
        self.cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_productos_nombre ON productos(nombre)"
        )
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS ventas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha TEXT,
                total REAL,
                estado TEXT DEFAULT 'Pagada',
                cliente_id INTEGER,
                Distribuidor_id INTEGER,
                vendedor_id INTEGER,
                extra TEXT,
                sincronizada BOOLEAN DEFAULT 0,
                FOREIGN KEY (cliente_id) REFERENCES clientes(id),
                FOREIGN KEY (Distribuidor_id) REFERENCES Distribuidores(id) ON DELETE RESTRICT,
                FOREIGN KEY (vendedor_id) REFERENCES trabajadores(id) ON DELETE RESTRICT
            )
        """)
        self.cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_ventas_cliente_id ON ventas(cliente_id)"
        )
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
                FOREIGN KEY (vendedor_id) REFERENCES trabajadores(id) ON DELETE SET NULL
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
        self.cursor.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_clientes_nit ON clientes(nit)"

        )
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
                detalles TEXT,
                FOREIGN KEY (venta_id) REFERENCES ventas(id)

            )
        """)
        self.ensure_column("notas", "detalles", "TEXT")
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
                FOREIGN KEY (Distribuidor_id) REFERENCES Distribuidores(id) ON DELETE RESTRICT,
                FOREIGN KEY (vendedor_id) REFERENCES vendedores(id) ON DELETE RESTRICT
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
            CREATE TABLE IF NOT EXISTS dte_correlativos (
                tipo TEXT NOT NULL,
                sucursal TEXT NOT NULL,
                punto TEXT NOT NULL,
                correlativo INTEGER NOT NULL,
                PRIMARY KEY (tipo, sucursal, punto)
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

        # Tabla de usuarios y cuentas por defecto
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS usuarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE,
                password TEXT NOT NULL,
                role TEXT CHECK(role IN ('admin','user','guest')) NOT NULL
            )
            """
        )
        self.conn.commit()
        self._ensure_default_users()

        # Si no hay registro, crea uno por defecto
        self.cursor.execute("SELECT COUNT(*) FROM Distribuidor_info")
        if self.cursor.fetchone()[0] == 0:
            self.cursor.execute("INSERT INTO Distribuidor_info (nombre) VALUES ('')")
            self.conn.commit()
        # Asegura columnas adicionales en tablas existentes
        columns = [
            ("productos", "precio_compra REAL DEFAULT 0"),
            ("productos", "precio_venta_minorista REAL DEFAULT 0"),
            ("productos", "precio_venta_mayorista REAL DEFAULT 0"),
            ("productos", "precio_total_mayorista REAL DEFAULT 0"),
            ("productos", "Distribuidor_id INTEGER"),
            ("ventas", "cliente_id INTEGER"),
            ("ventas", "Distribuidor_id INTEGER"),
            ("ventas", "vendedor_id INTEGER"),
            ("compras", "Distribuidor_id INTEGER"),
            ("compras", "comision_pct REAL DEFAULT 0"),
            ("compras", "comision_monto REAL DEFAULT 0"),
            ("detalles_compra", "fecha_vencimiento TEXT"),
            ("vendedores", "descripcion TEXT"),
            ("vendedores", "codigo TEXT"),
            ("vendedores", "Distribuidor_id INTEGER"),
            ("vendedores", "dui TEXT"),
            ("trabajadores", "codigo TEXT"),
            ("detalles_compra", "descuento REAL DEFAULT 0"),
            ("detalles_compra", "descuento_tipo TEXT"),
            ("detalles_compra", "iva REAL DEFAULT 0"),
            ("detalles_compra", "iva_tipo TEXT"),
            ("detalles_compra", "comision_pct REAL DEFAULT 0"),
            ("detalles_compra", "comision_monto REAL DEFAULT 0"),
            ("detalles_compra", "comision_tipo TEXT"),
            ("detalles_venta", "descuento REAL DEFAULT 0"),
            ("detalles_venta", "descuento_tipo TEXT"),
            ("detalles_venta", "iva REAL DEFAULT 0"),
            ("detalles_venta", "comision REAL DEFAULT 0"),
            ("detalles_venta", "iva_tipo TEXT"),
            ("detalles_venta", "tipo_fiscal TEXT"),
            ("ventas_credito_fiscal", "sumas REAL DEFAULT 0"),
            ("ventas_credito_fiscal", "iva REAL DEFAULT 0"),
            ("ventas_credito_fiscal", "subtotal REAL DEFAULT 0"),
            ("ventas_credito_fiscal", "total_letras TEXT"),
            ("ventas_credito_fiscal", "descuentos REAL DEFAULT 0"),
            ("ventas", "extra TEXT"),
            ("ventas", "estado TEXT DEFAULT 'Pagada'"),
            ("ventas", "sincronizada BOOLEAN DEFAULT 0"),
            ("detalles_venta", "extra TEXT"),
            ("ventas_credito_fiscal", "extra TEXT"),
            ("ventas_credito_fiscal", "ventas_exentas REAL DEFAULT 0"),
            ("ventas_credito_fiscal", "ventas_no_sujetas REAL DEFAULT 0"),
            ("detalles_venta", "precio_con_iva REAL DEFAULT 0"),
            ("detalles_venta", "vendedor_id INTEGER"),
            ("productos", "sku TEXT"),
        ]
        for table, definition in columns:
            self.add_column_if_missing(table, definition)
        # Create index for SKU only if the column exists
        self.cursor.execute("PRAGMA table_info(productos)")
        if any(row[1] == "sku" for row in self.cursor.fetchall()):
            self.cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_productos_sku ON productos(sku)"
            )
        # Índices únicos para campos de texto
        self.cursor.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_clientes_codigo ON clientes(codigo)"
        )
        self.cursor.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_vendedores_codigo ON vendedores(codigo)"
        )
        self.cursor.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_trabajadores_codigo ON trabajadores(codigo)"
        )
        self.cursor.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_distribuidores_codigo ON Distribuidores(codigo)"
        )
        self.cursor.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_distribuidores_nombre ON Distribuidores(nombre)"
        )
        self.ensure_vendedores_trabajadores()
        self.migrate_ventas_cliente_fk()
        self.migrate_detalles_venta_vendedor_fk()
        self.conn.commit()

        # Verifica que la columna estado exista en ventas
        self.ensure_column("ventas", "estado", "TEXT DEFAULT 'Pagada'")
        self.ensure_column("ventas", "sincronizada", "BOOLEAN DEFAULT 0")

    # CRUD Distribuidores
    def add_Distribuidor(self, nombre, commit: bool = True):
        """Insert a new distributor.

        Parameters
        ----------
        nombre: str
            Distributor name.
        commit: bool, optional
            If ``True`` (default) the change is committed immediately.  When
            executing inside a larger transaction set this to ``False`` to
            defer the commit.
        """

        self.cursor.execute("INSERT INTO Distribuidores (nombre) VALUES (?)", (nombre,))
        if commit:
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

    def delete_Distribuidor(self, id, reassign_to=...):
        tables = {
            "vendedores": "Distribuidor_id",
            "productos": "Distribuidor_id",
            "compras": "Distribuidor_id",
            "ventas": "Distribuidor_id",
        }
        try:
            counts = []
            for table, column in tables.items():
                self.cursor.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE {column}=?", (id,)
                )
                counts.append(self.cursor.fetchone()[0])
            if any(counts):
                if reassign_to is ...:
                    raise ValueError(
                        "No se puede eliminar distribuidor con registros asociados"
                    )
                for table, column in tables.items():
                    self.cursor.execute(
                        f"UPDATE {table} SET {column}=? WHERE {column}=?", (reassign_to, id)
                    )
            self.cursor.execute("DELETE FROM Distribuidores WHERE id=?", (id,))
            self.conn.commit()
        except ValueError:
            raise
        except Exception as e:
            logger.exception("Error al eliminar Distribuidor: %s", e)
            raise

    # CRUD VENDEDORES (antes vendedores)
    def add_vendedor(
        self,
        nombre,
        descripcion: str = "",
        Distribuidor_id=None,
        codigo=None,
        dui=None,
        commit: bool = True,
        trabajador_id=None,
    ):
        """Insert a new vendor.

        ``commit`` can be set to ``False`` when called inside an existing
        transaction to avoid committing after each insertion.

        If ``trabajador_id`` is provided, the corresponding record in
        ``trabajadores`` will be updated (and marked as vendor) instead of
        inserting a new one.
        """
        if codigo is None:
            codigo = self.get_next_vendedor_codigo()

        self.cursor.execute(
            "SELECT 1 FROM trabajadores WHERE codigo=?",
            (codigo,),
        )
        if self.cursor.fetchone():
            raise ValueError("El código ya existe")

        self.cursor.execute(
            """
            INSERT INTO trabajadores (codigo, nombre, dui, es_vendedor)
            VALUES (?, ?, ?, 1)
            """,
            (codigo, nombre, dui),
        )
        trabajador_id = self.cursor.lastrowid

        self.cursor.execute(
            "INSERT INTO vendedores (id, codigo, nombre, dui, descripcion, Distribuidor_id) VALUES (?, ?, ?, ?, ?, ?)",
            (trabajador_id, codigo, nombre, dui, descripcion, Distribuidor_id),
        )
        if commit:
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
            self.cursor.execute(
                "UPDATE trabajadores SET codigo=?, nombre=?, dui=? WHERE id=?",
                (codigo, nombre, dui, id),
            )
            self.conn.commit()
        except Exception as e:
            logger.exception("Error al actualizar vendedor: %s", e)

    def delete_vendedor(self, id, reassign_to=...):
        tables = {
            "productos": "vendedor_id",
            "compras": "vendedor_id",
            "ventas": "vendedor_id",
            "detalles_venta": "vendedor_id",
        }
        try:
            counts = []
            for table, column in tables.items():
                self.cursor.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE {column}=?", (id,)
                )
                counts.append(self.cursor.fetchone()[0])
            if any(counts):
                if reassign_to is ...:
                    raise ValueError(
                        "No se puede eliminar vendedor con registros asociados"
                    )
                for table, column in tables.items():
                    self.cursor.execute(
                        f"UPDATE {table} SET {column}=? WHERE {column}=?", (reassign_to, id)
                    )
            self.cursor.execute("DELETE FROM vendedores WHERE id=?", (id,))
            self.cursor.execute("DELETE FROM trabajadores WHERE id=?", (id,))
            self.conn.commit()
        except ValueError:
            raise
        except Exception as e:
            logger.exception("Error al eliminar vendedor: %s", e)
            raise

    # CRUD PRODUCTOS
    def add_producto(
        self,
        nombre,
        codigo,
        sku,
        vendedor_id,
        Distribuidor_id,
        precio_compra,
        precio_venta_minorista,
        precio_venta_mayorista,
        stock,
        commit: bool = True,
    ):
        """Insert a product into the database.

        Parameters
        ----------
        commit: bool, optional
            If ``False`` the insertion is not committed immediately.  This is
            useful when the caller manages the transaction manually.
        """

        # Elimina fecha_vencimiento del método y de la consulta
        self.cursor.execute(
            "INSERT INTO productos (nombre, codigo, sku, vendedor_id, Distribuidor_id, precio_compra, precio_venta_minorista, precio_venta_mayorista, stock) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (nombre, codigo, sku, vendedor_id, Distribuidor_id, precio_compra, precio_venta_minorista, precio_venta_mayorista, stock)
        )
        if commit:
            self.conn.commit()

    def get_productos(
        self,
        vendedor_id=None,
        Distribuidor_id=None,
        search="",
        limit=None,
        offset=0,
    ):
        """Retrieve products with optional pagination."""
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
            filtros.append("(nombre LIKE ? OR codigo LIKE ? OR sku LIKE ?)")
            params.extend([f"%{search}%", f"%{search}%", f"%{search}%"])
        if filtros:
            query += " WHERE " + " AND ".join(filtros)
        if limit is not None:
            query += " LIMIT ? OFFSET ?"
            params.extend([limit, offset])
        self.cursor.execute(query, params)
        return [dict(row) for row in self.cursor.fetchall()]

    def edit_producto(self, producto_id, nombre, codigo, sku, vendedor_id, Distribuidor_id, precio_compra, precio_venta_minorista, precio_venta_mayorista, stock):
        # Elimina fecha_vencimiento del método y de la consulta
        self.cursor.execute(
            "UPDATE productos SET nombre=?, codigo=?, sku=?, vendedor_id=?, Distribuidor_id=?, precio_compra=?, precio_venta_minorista=?, precio_venta_mayorista=?, stock=? WHERE id=?",
            (nombre, codigo, sku, vendedor_id, Distribuidor_id, precio_compra, precio_venta_minorista, precio_venta_mayorista, stock, producto_id)
        )
        self.conn.commit()

    def delete_producto(self, producto_id):
        self.cursor.execute(
            "DELETE FROM detalles_venta WHERE producto_id=?", (producto_id,)
        )
        self.cursor.execute(
            "DELETE FROM detalles_compra WHERE producto_id=?", (producto_id,)
        )
        self.cursor.execute(
            "DELETE FROM compras WHERE producto_id=?", (producto_id,)
        )
        self.cursor.execute(
            "DELETE FROM movimientos WHERE producto_id=?", (producto_id,)
        )
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
        # Asegura que las columnas requeridas existan antes de insertar
        self.ensure_column("ventas", "estado", "TEXT DEFAULT 'Pagada'")
        self.ensure_column("ventas", "sincronizada", "INTEGER DEFAULT 1")
        extra_json = json.dumps(extra) if extra is not None else None
        columns = ["fecha", "total", "estado", "sincronizada"]
        values = [fecha, total, estado, 1]
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
        # Asegura que las columnas requeridas existan antes de insertar
        self.ensure_column("ventas", "estado", "TEXT DEFAULT 'Pagada'")
        self.ensure_column("ventas", "sincronizada", "INTEGER DEFAULT 1")
        self.ensure_column("ventas_credito_fiscal", "documento_venta_a_cuenta", "TEXT")
        try:
            cols = ["fecha", "total", "cliente_id", "estado", "sincronizada"]
            vals = [fecha, total, cliente_id, estado, 1]
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


    def get_ventas(self, sincronizada: int | None = None):
        """Return sales, optionally filtered by ``sincronizada`` flag."""
        if sincronizada is None:
            self.cursor.execute("SELECT * FROM ventas")
        else:
            self.cursor.execute(
                "SELECT * FROM ventas WHERE sincronizada=?", (sincronizada,)
            )
        return [dict(row) for row in self.cursor.fetchall()]

    def get_venta_by_id(self, venta_id: int):
        """Fetch a single sale by its ID."""
        self.cursor.execute("SELECT * FROM ventas WHERE id=?", (venta_id,))
        row = self.cursor.fetchone()
        if row:
            data = dict(row)
            try:
                data["id"] = int(data["id"])
            except (ValueError, TypeError):
                pass
            return data
        return None

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
            self.cursor.execute(
                "DELETE FROM detalles_venta WHERE venta_id=?",
                (id,),
            )
            self.cursor.execute(
                "DELETE FROM notas WHERE venta_id=?",
                (id,),
            )
            self.cursor.execute(
                "DELETE FROM ventas_credito_fiscal WHERE venta_id=?",
                (id,),
            )
            self.cursor.execute(
                "DELETE FROM facturas_pdf WHERE venta_id=?",
                (id,),
            )
            self.cursor.execute(
                "DELETE FROM tickets_pdf WHERE venta_id=?",
                (id,),
            )
            self.cursor.execute(
                "DELETE FROM dte_envios WHERE venta_id=?",
                (id,),
            )
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
        self.cursor.close()
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
    def nit_exists(self, nit, exclude_id=None):
        """Check if a NIT already exists in the clientes table.

        Args:
            nit: NIT value to check. Empty values are ignored.
            exclude_id: Optional client ID to exclude from the check.

        Returns:
            bool: True if the NIT exists for another client.
        """
        if not nit:
            return False
        query = "SELECT 1 FROM clientes WHERE nit=?"
        params = [nit]
        if exclude_id is not None:
            query += " AND id<>?"
            params.append(exclude_id)
        self.cursor.execute(query, params)
        return self.cursor.fetchone() is not None

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
        commit: bool = True,
    ):
        if codigo is None:
            codigo = self.get_next_cliente_codigo()
        nit = nit.strip() if isinstance(nit, str) else nit
        nit = nit or None
        if self.nit_exists(nit):
            raise ValueError("El NIT ya existe")
        self.cursor.execute(
            """
            INSERT INTO clientes (codigo, nombre, nrc, nit, dui, giro, telefono, email, direccion, departamento, municipio)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (codigo, nombre, nrc, nit, dui, giro, telefono, email, direccion, departamento, municipio),
        )
        if commit:
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
        nit = nit.strip() if isinstance(nit, str) else nit
        nit = nit or None
        if self.nit_exists(nit, exclude_id=id):
            raise ValueError("El NIT ya existe")
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
        self.cursor.execute("DELETE FROM pagos WHERE cliente_id=?", (id,))
        self.cursor.execute(
            "UPDATE ventas SET cliente_id=NULL WHERE cliente_id=?",
            (id,),
        )
        self.cursor.execute(
            "UPDATE ventas_credito_fiscal SET cliente_id=NULL WHERE cliente_id=?",
            (id,),
        )
        self.cursor.execute("DELETE FROM clientes WHERE id=?", (id,))
        self.conn.commit()

    def get_clientes(self, search=""):
        query = (
            "SELECT id, codigo, nombre, nrc, nit, dui, telefono, email, giro, direccion, departamento, municipio, otros "
            "FROM clientes"
        )
        params = []
        if search:
            like = f"%{search}%"
            query += (
                " WHERE nombre LIKE ? OR codigo LIKE ? OR nit LIKE ? OR nrc LIKE ? "
                "OR dui LIKE ? OR telefono LIKE ? OR email LIKE ?"
            )
            params = [like, like, like, like, like, like, like]
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

    def next_dte_correlativo(self, tipo: str, sucursal: str, punto: str) -> int:
        """Obtiene y actualiza el correlativo para la combinación dada."""
        with self.lock:
            with self.conn:
                self.cursor.execute(
                    "SELECT correlativo FROM dte_correlativos WHERE tipo=? AND sucursal=? AND punto=?",
                    (tipo, sucursal, punto),
                )
                row = self.cursor.fetchone()
                if row:
                    correlativo = int(row["correlativo"]) + 1
                    self.cursor.execute(
                        "UPDATE dte_correlativos SET correlativo=? WHERE tipo=? AND sucursal=? AND punto=?",
                        (correlativo, tipo, sucursal, punto),
                    )
                else:
                    correlativo = 1
                    self.cursor.execute(
                        "INSERT INTO dte_correlativos (tipo, sucursal, punto, correlativo) VALUES (?, ?, ?, ?)",
                        (tipo, sucursal, punto, correlativo),
                    )
            return correlativo

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

    def limpiar_inventario(self):
        """Elimina ventas, compras y movimientos de forma atómica.

        Se utilizan transacciones explícitas para asegurar que si ocurre un
        error al borrar alguna tabla el estado de la base de datos se
        restablezca mediante ``ROLLBACK``.
        """
        with self.lock:
            try:
                self.cursor.execute("BEGIN")
                tables = [
                    # child tables first
                    "detalles_venta",
                    "detalles_compra",
                    "movimientos",
                    "notas",
                    "facturas_pdf",
                    "tickets_pdf",
                    "dte_envios",
                    "ventas_credito_fiscal",
                    "pagos",
                    # then parent tables
                    "ventas",
                    "compras",
                    "trabajadores",
                    "clientes",
                ]
                for table in tables:
                    self.cursor.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                        (table,),
                    )
                    if self.cursor.fetchone():
                        self.cursor.execute(f"DELETE FROM {table}")
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise

    def limpiar_productos(self):
        """Remove all products and their dependent records.

        The operation runs inside an explicit transaction to avoid
        inconsistent intermediate states.  All rows referencing
        ``producto_id`` in other tables are removed before deleting from
        ``productos`` itself.
        """
        try:
            self.cursor.execute("BEGIN")

            # Known dependent tables are deleted first.
            dependent_tables = [
                "detalles_venta",
                "detalles_compra",
                "compras",
                "movimientos",
            ]

            # Include any additional table that has a ``producto_id`` column.
            self.cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
            for row in self.cursor.fetchall():
                table = row[0]
                if table == "productos" or table in dependent_tables:
                    continue
                self.cursor.execute(f"PRAGMA table_info({table})")
                if any(col[1] == "producto_id" for col in self.cursor.fetchall()):
                    dependent_tables.append(table)

            for table in dependent_tables:
                self.cursor.execute(f"DELETE FROM {table}")

            self.cursor.execute("DELETE FROM productos")
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def limpiar_vendedores(self):
        self.cursor.execute("DELETE FROM vendedores")
        self.conn.commit()

    def limpiar_Distribuidores(self):
        self.cursor.execute("DELETE FROM Distribuidores")
        self.conn.commit()

    def limpiar_ventas_credito_fiscal(self):
        self.cursor.execute("DELETE FROM ventas_credito_fiscal")
        self.conn.commit()

    def limpiar_ventas_huerfanas(self):
        """Remove sales that have no related records in dependent tables."""
        self.cursor.execute(
            """
            DELETE FROM ventas
            WHERE id NOT IN (SELECT DISTINCT venta_id FROM detalles_venta)
              AND id NOT IN (SELECT DISTINCT venta_id FROM ventas_credito_fiscal)
              AND id NOT IN (SELECT DISTINCT venta_id FROM dte_envios)
              AND id NOT IN (SELECT DISTINCT venta_id FROM notas)
              AND id NOT IN (SELECT DISTINCT venta_id FROM facturas_pdf)
              AND id NOT IN (SELECT DISTINCT venta_id FROM tickets_pdf)
            """
        )
        self.conn.commit()

    def add_Distribuidor_detallado(self, data, commit: bool = True):
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
        if commit:
            self.conn.commit()

    def add_compra_detallada(self, data, commit: bool = True):
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
        if commit:
            self.conn.commit()
        return self.cursor.lastrowid  # <-- RETORNA EL ID

    def add_detalle_compra(
        self,
        compra_id,
        producto_id,
        cantidad,
        precio_unitario,
        fecha_vencimiento="",
        descuento=0,
        descuento_tipo="",
        iva=0,
        iva_tipo="",
        comision_pct=0,
        comision_monto=0,
        comision_tipo="",
        commit: bool = True,
    ):
        self.cursor.execute("""
            INSERT INTO detalles_compra (
                compra_id, producto_id, cantidad, precio_unitario, fecha_vencimiento,
                descuento, descuento_tipo, iva, iva_tipo, comision_pct, comision_monto, comision_tipo
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            compra_id, producto_id, cantidad, precio_unitario, fecha_vencimiento,
            descuento, descuento_tipo, iva, iva_tipo, comision_pct, comision_monto, comision_tipo
        ))
        if commit:
            self.conn.commit()


    def add_movimiento(
        self,
        fecha,
        tipo,
        producto_id,
        cantidad,
        motivo="",
        usuario="",
        commit: bool = True,
    ):
        self.cursor.execute("""
            INSERT INTO movimientos (fecha, tipo, producto_id, cantidad, motivo, usuario)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (fecha, tipo, producto_id, cantidad, motivo, usuario))
        if commit:
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
        cols = ["fecha", "total", "estado", "sincronizada"]
        vals = [fecha, total, estado, 1]
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

    def add_trabajador(self, data, commit: bool = True):
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
        if commit:
            self.conn.commit()

    def get_trabajadores(self, solo_vendedores=False, area=None, search=""):
        query = "SELECT * FROM trabajadores"
        params = []
        filtros = []
        if solo_vendedores:
            filtros.append("es_vendedor=1")
        if area:
            filtros.append("LOWER(area) LIKE LOWER(?)")
            params.append(f"%{area}%")
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
        self.cursor.execute(
            "SELECT COUNT(*) FROM ventas WHERE vendedor_id=?",
            (id,),
        )
        if self.cursor.fetchone()[0] > 0:
            raise ValueError(
                "No se puede eliminar el trabajador: tiene ventas asociadas"
            )
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
        if tipo not in ("credito", "debito", "remision"):
            raise ValueError("tipo debe ser 'credito', 'debito' o 'remision'")

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

    def listar_dtes(self, fecha_inicio=None, fecha_fin=None, estado=None):
        """Lista registros de ``dte_envios`` filtrando por fecha y estado."""
        self.ensure_column("dte_envios", "respuesta", "TEXT")
        query = "SELECT * FROM dte_envios WHERE 1=1"
        params = []
        if fecha_inicio:
            query += " AND date(fecha_hora) >= date(?)"
            params.append(fecha_inicio)
        if fecha_fin:
            query += " AND date(fecha_hora) <= date(?)"
            params.append(fecha_fin)
        if estado:
            query += " AND estado = ?"
            params.append(estado)
        query += " ORDER BY fecha_hora"
        self.cursor.execute(query, params)
        return [dict(row) for row in self.cursor.fetchall()]

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

    # ---- Gestión de usuarios ----

    def get_users(self):
        self.cursor.execute("SELECT id, username, role FROM usuarios")
        return [dict(row) for row in self.cursor.fetchall()]

    def get_user(self, user_id):
        self.cursor.execute(
            "SELECT id, username, password, role FROM usuarios WHERE id=?",
            (user_id,),
        )
        row = self.cursor.fetchone()
        return dict(row) if row else None

    def add_user(self, username, password, role):
        self.cursor.execute(
            "INSERT INTO usuarios (username, password, role) VALUES (?, ?, ?)",
            (username, password, role),
        )
        self.conn.commit()

    def update_user(self, user_id, username, password, role):
        self.cursor.execute(
            "UPDATE usuarios SET username=?, password=?, role=? WHERE id=?",
            (username, password, role, user_id),
        )
        self.conn.commit()

    def delete_user(self, user_id):
        self.cursor.execute("DELETE FROM usuarios WHERE id=?", (user_id,))
        self.conn.commit()

    def authenticate(self, username, password):
        self.cursor.execute(
            "SELECT id, username, role FROM usuarios WHERE username=? AND password=?",
            (username, password),
        )
        row = self.cursor.fetchone()
        return dict(row) if row else None
