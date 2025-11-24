import os
import re
import shutil
import sqlite3
from datetime import date, datetime, timezone
import json
import logging
import threading
import unicodedata
from pathlib import Path
from decimal import Decimal
from typing import Any, Callable, Mapping, Optional

from utils import versioned_dte
from utils.fiscal_extra import build_fiscal_extra, normalize_tipo_fiscal
from utils.line_totals import compute_line_totals
from utils.monto import d8
from utils.snapshot import Snapshot
from utils.fecha import fecha_ddmmaaaa, normalizar_fecha_iso
from utils.stable_json import stable_stringify
from paths import DTES_DIR, get_canonical_dte_dir, user_data_path

logger = logging.getLogger(__name__)


def _normalize_sku_value(value):
    if isinstance(value, str):
        trimmed = value.strip()
        return trimmed or None
    return value if value else None


_CODE_TO_CANONICAL = {
    "01": "ConsumidorFinal",
    "1": "ConsumidorFinal",
    "cf": "ConsumidorFinal",
    "consumidorfinal": "ConsumidorFinal",
    "consumidor final": "ConsumidorFinal",
    "factura consumidor final": "ConsumidorFinal",
    "03": "CreditoFiscal",
    "3": "CreditoFiscal",
    "ccf": "CreditoFiscal",
    "credito fiscal": "CreditoFiscal",
    "credito fiscal electronico": "CreditoFiscal",
    "crédito fiscal": "CreditoFiscal",
    "factura credito fiscal": "CreditoFiscal",
    "04": "NotaRemision",
    "4": "NotaRemision",
    "nota remision": "NotaRemision",
    "nota de remision": "NotaRemision",
    "nota de remisión": "NotaRemision",
    "05": "NotaCredito",
    "5": "NotaCredito",
    "nota credito": "NotaCredito",
    "nota de credito": "NotaCredito",
    "nota de crédito": "NotaCredito",
    "nc": "NotaCredito",
    "06": "NotaDebito",
    "6": "NotaDebito",
    "nota debito": "NotaDebito",
    "nota de debito": "NotaDebito",
    "nota de débito": "NotaDebito",
    "nd": "NotaDebito",
}

_PATH_HINTS = {
    "facturas_consumidor_final": "ConsumidorFinal",
    "consumidor_final": "ConsumidorFinal",
    "consumidorfinal": "ConsumidorFinal",
    "facturas_credito_fiscal": "CreditoFiscal",
    "credito_fiscal": "CreditoFiscal",
    "creditofiscal": "CreditoFiscal",
    "notas_credito": "NotaCredito",
    "nota_credito": "NotaCredito",
    "notacredito": "NotaCredito",
    "notas_debito": "NotaDebito",
    "nota_debito": "NotaDebito",
    "notadebito": "NotaDebito",
    "notas_remision": "NotaRemision",
    "nota_remision": "NotaRemision",
    "notaremision": "NotaRemision",
}

_CANONICAL_TYPES = {
    "ConsumidorFinal",
    "CreditoFiscal",
    "NotaCredito",
    "NotaDebito",
    "NotaRemision",
}


def _parse_cliente_otros(raw_otros):
    if not raw_otros:
        return {}
    if isinstance(raw_otros, Mapping):
        return dict(raw_otros)
    if isinstance(raw_otros, str):
        try:
            data = json.loads(raw_otros)
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}
    return {}


def _serialize_cliente_otros(extras: Mapping[str, Any] | None) -> str | None:
    if not extras:
        return None
    cleaned = {
        key: value
        for key, value in extras.items()
        if value not in (None, "")
    }
    if not cleaned:
        return None
    try:
        return json.dumps(cleaned, ensure_ascii=False)
    except Exception:
        return None


def _apply_cliente_extras(cliente: Mapping[str, Any]) -> dict[str, Any]:
    data = dict(cliente)
    extras = _parse_cliente_otros(data.get("otros"))
    tipo = extras.get("tipoContribuyente") or data.get("tipoContribuyente")
    if not tipo:
        tipo = "Persona Natural"
    data["tipoContribuyente"] = tipo
    razon = extras.get("razonSocial")
    if not razon:
        razon = data.get("nombreComercial", "")
    data["razonSocial"] = razon
    return data

class CommitAwareConnection(sqlite3.Connection):
    """SQLite connection that notifies listeners after write commits."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._after_commit_callbacks: list[Callable[[], None]] = []
        self._last_total_changes = self.total_changes

    def add_after_commit_callback(self, callback: Callable[[], None]) -> None:
        if callback in self._after_commit_callbacks:
            return
        self._after_commit_callbacks.append(callback)

    def remove_after_commit_callback(self, callback: Callable[[], None]) -> None:
        try:
            self._after_commit_callbacks.remove(callback)
        except ValueError:
            pass

    def commit(self) -> None:  # type: ignore[override]
        super().commit()
        current_changes = self.total_changes
        changed = current_changes != self._last_total_changes
        self._last_total_changes = current_changes
        if not changed:
            return
        for callback in tuple(self._after_commit_callbacks):
            try:
                callback()
            except Exception:
                logger.exception("Error en callback posterior al commit")


class DB:
    def __init__(self, db_name: str | Path | None = None):
        if db_name is None:
            db_path = user_data_path("inventario.db")
        else:
            db_path = Path(db_name)
        self.is_memory_db = str(db_path) == ":memory:"
        if not self.is_memory_db:
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        # ``check_same_thread=False`` allows the connection to be used from
        # multiple threads.  Each thread should ideally use its own connection
        # but this flag prevents SQLite from raising an exception if a
        # connection crosses thread boundaries.
        self.conn: CommitAwareConnection = sqlite3.connect(
            db_path,
            check_same_thread=False,
            factory=CommitAwareConnection,
        )
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.row_factory = sqlite3.Row
        # Simple mutex to guard database operations when the same connection is
        # accessed from multiple threads. Threads may also create their own
        # ``DB`` instances to keep connections separate.
        self.lock = threading.Lock()
        self.cursor = self.conn.cursor()
        self._retenciones_cr_initialized = False
        self._after_commit_callbacks: list[Callable[[], None]] = []
        try:
            self.conn.add_after_commit_callback(self._run_after_commit_callbacks)
        except AttributeError:
            logger.debug("La conexión no soporta callbacks posteriores al commit")
        self.setup()
        # ``extra`` se introdujo como un JSON con información adicional de la
        # venta.  Garantizamos que la columna exista incluso en bases antiguas
        # para evitar fallos al guardar nuevos totales fiscales.
        self.ensure_column("ventas", "extra", "TEXT")
        try:
            self.backfill_ventas_extra()
        except Exception:
            logger.exception("No se pudo ejecutar el backfill de ventas.extra")

        try:
            self.migrate_facturas_pdf_paths()
        except Exception:
            logger.exception(
                "No se pudo migrar las rutas de facturas a la ubicación canónica"
            )

    def _run_after_commit_callbacks(self) -> None:
        for callback in tuple(self._after_commit_callbacks):
            try:
                callback()
            except Exception:
                logger.exception("Error en callback posterior al commit (DB)")

    def add_after_commit_callback(self, callback: Callable[[], None]) -> None:
        if callback in self._after_commit_callbacks:
            return
        self._after_commit_callbacks.append(callback)

    def remove_after_commit_callback(self, callback: Callable[[], None]) -> None:
        try:
            self._after_commit_callbacks.remove(callback)
        except ValueError:
            pass

    @staticmethod
    def _paths_equal(first: os.PathLike | str | None, second: os.PathLike | str | None) -> bool:
        if first is None or second is None:
            return False
        try:
            return os.path.abspath(os.fspath(first)) == os.path.abspath(os.fspath(second))
        except (TypeError, ValueError, OSError):  # pragma: no cover - defensive
            return False

    @staticmethod
    def _simplify_label(value: os.PathLike | str | None) -> str | None:
        if value is None:
            return None
        try:
            text = os.fspath(value)
        except TypeError:
            return None
        text = text.strip()
        if not text:
            return None
        if text in _CANONICAL_TYPES:
            return text
        lowered = text.lower()
        for canonical in _CANONICAL_TYPES:
            if lowered == canonical.lower():
                return canonical
        normalized = unicodedata.normalize("NFKD", text)
        cleaned = []
        for char in normalized:
            if unicodedata.combining(char):
                continue
            if char.isalnum():
                cleaned.append(char.lower())
            else:
                cleaned.append(" ")
        simplified = re.sub(r"\s+", " ", "".join(cleaned)).strip()
        if not simplified:
            return None
        mapped = _CODE_TO_CANONICAL.get(simplified)
        if mapped:
            return mapped
        if simplified.isdigit():
            mapped = _CODE_TO_CANONICAL.get(simplified.zfill(2))
            if mapped:
                return mapped
        if "nota" in simplified and "credito" in simplified:
            return "NotaCredito"
        if "nota" in simplified and "debito" in simplified:
            return "NotaDebito"
        if "nota" in simplified and "remision" in simplified:
            return "NotaRemision"
        if "credito" in simplified:
            return "CreditoFiscal"
        if "consumidor" in simplified:
            return "ConsumidorFinal"
        return None

    def _guess_doc_type(self, tipo: os.PathLike | str | None, ruta: os.PathLike | str | None) -> str | None:
        canonical = self._simplify_label(tipo)
        if canonical:
            return canonical
        if ruta:
            try:
                ruta_text = os.fspath(ruta).lower()
            except TypeError:
                ruta_text = ""
            for hint, mapped in _PATH_HINTS.items():
                if hint in ruta_text:
                    return mapped
        return None

    def _find_json_sidecar(self, pdf_path: Path | None) -> Path | None:
        if not pdf_path:
            return None
        stem = pdf_path.stem
        parent = pdf_path.parent
        for suffix in (".json", ".JSON", ".Json", ".JsON"):
            candidate = parent / f"{stem}{suffix}"
            if candidate.exists():
                return candidate
        return None

    def _sync_invoice_json(self, original_pdf: Path | None, dest_pdf: Path) -> None:
        json_source = None
        for candidate in (original_pdf, dest_pdf):
            sidecar = self._find_json_sidecar(candidate)
            if sidecar:
                json_source = sidecar
                break
        if not json_source:
            return
        dest_json = dest_pdf.with_suffix(".json")
        if self._paths_equal(json_source, dest_json):
            return
        try:
            dest_json.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(json_source, dest_json)
        except Exception:
            logger.warning(
                "No se pudo copiar JSON asociado a la factura: %s",
                dest_json,
                exc_info=True,
            )

    def _ensure_invoice_files(self, source_path: Path | None, dest_path: Path) -> bool:
        dest_path = Path(dest_path)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        source_exists = source_path.exists() if source_path else False
        dest_exists = dest_path.exists()
        if source_exists and not self._paths_equal(source_path, dest_path):
            try:
                shutil.copy2(source_path, dest_path)
                dest_exists = True
            except Exception:
                logger.warning(
                    "No se pudo copiar PDF a ubicación canónica: %s",
                    dest_path,
                    exc_info=True,
                )
        elif not source_exists and not dest_exists:
            return False

        self._sync_invoice_json(source_path if source_path else None, dest_path)
        return dest_path.exists()

    def _compute_invoice_destination(
        self, tipo: os.PathLike | str | None, ruta: os.PathLike | str | None
    ) -> Path | None:
        canonical = self._guess_doc_type(tipo, ruta)
        if not canonical:
            return None
        try:
            filename = Path(os.fspath(ruta)).name
        except (TypeError, ValueError, OSError):
            return None
        try:
            target_dir = get_canonical_dte_dir(canonical)
        except Exception:
            return None
        return target_dir / filename

    def migrate_facturas_pdf_paths(self) -> None:
        self.cursor.execute(
            "SELECT id, venta_id, tipo, ruta FROM facturas_pdf WHERE ruta IS NOT NULL"
        )
        rows = self.cursor.fetchall()
        updated = 0
        for row in rows:
            ruta = row["ruta"]
            destino = self._compute_invoice_destination(row["tipo"], ruta)
            if not destino:
                continue
            destino_str = os.fspath(destino)
            if self._paths_equal(ruta, destino_str):
                continue
            try:
                source_path = Path(os.fspath(ruta)) if ruta else None
            except (TypeError, ValueError, OSError):
                source_path = None
            if not self._ensure_invoice_files(source_path, destino):
                if not destino.exists():
                    continue
            self.cursor.execute(
                "UPDATE facturas_pdf SET ruta=? WHERE id=?",
                (destino_str, row["id"]),
            )
            updated += 1
        if updated:
            self.conn.commit()
            logger.info("Rutas de facturas migradas: %s", updated)

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

    def _ensure_retenciones_cr_table(self) -> None:
        """Create storage for Comprobantes de Retención if missing."""

        if getattr(self, "_retenciones_cr_initialized", False):
            return
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS retenciones_cr (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                venta_id INTEGER NOT NULL,
                payload_json TEXT NOT NULL,
                jws TEXT,
                estado TEXT,
                sello TEXT,
                respuesta TEXT,
                codigo_generacion TEXT NOT NULL,
                numero_control TEXT NOT NULL,
                codigo_generacion_origen TEXT NOT NULL,
                numero_control_origen TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                enviado_en TEXT,
                FOREIGN KEY (venta_id) REFERENCES ventas(id) ON DELETE CASCADE
            )
            """
        )
        self.cursor.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_retenciones_cr_venta ON retenciones_cr(venta_id)"
        )
        self.cursor.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_retenciones_cr_cod ON retenciones_cr(UPPER(codigo_generacion))"
        )
        self.cursor.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_retenciones_cr_ctrl ON retenciones_cr(UPPER(numero_control))"
        )
        self.cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_retenciones_cr_cod_origen ON retenciones_cr(UPPER(codigo_generacion_origen))"
        )
        self.cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_retenciones_cr_ctrl_origen ON retenciones_cr(UPPER(numero_control_origen))"
        )
        self.conn.commit()
        self._retenciones_cr_initialized = True

    def _has_table(self, table: str) -> bool:
        """Return ``True`` if ``table`` exists in the current database."""

        try:
            self.cursor.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
            )
            return self.cursor.fetchone() is not None
        except sqlite3.Error:
            return False

    def _has_column(self, table: str, column: str) -> bool:
        """Return ``True`` if ``column`` exists in ``table``."""

        try:
            self.cursor.execute(f"PRAGMA table_info({table})")
        except sqlite3.Error:
            return False
        return any(row[1] == column for row in self.cursor.fetchall())

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
                nombreComercial TEXT,
                nrc TEXT,
                nit TEXT,
                dui TEXT,
                giro TEXT,
                codActividad TEXT,
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
        self.ensure_column("clientes", "codActividad", "TEXT")
        self.ensure_column("clientes", "nombreComercial", "TEXT")
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
                codigo_lote TEXT,
                registro_sanitario TEXT,
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
            CREATE TABLE IF NOT EXISTS dte_pendientes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                venta_id INTEGER,
                dte_json TEXT,
                modo TEXT,
                fecha_creacion TEXT,
                transmitido INTEGER DEFAULT 0
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
                respuesta TEXT
            )
            """
        )
        self.conn.commit()
        self._ensure_retenciones_cr_table()

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
            ("detalles_compra", "codigo_lote TEXT"),
            ("detalles_compra", "registro_sanitario TEXT"),
            ("detalles_venta", "descuento REAL DEFAULT 0"),
            ("detalles_venta", "descuento_tipo TEXT"),
            ("detalles_venta", "iva REAL DEFAULT 0"),
            ("detalles_venta", "comision REAL DEFAULT 0"),
            ("detalles_venta", "iva_tipo TEXT"),
            ("detalles_venta", "tipo_fiscal TEXT"),
            ("detalles_venta", "desc_con_iva REAL DEFAULT 0"),
            ("detalles_venta", "base REAL DEFAULT 0"),
            ("detalles_venta", "total REAL DEFAULT 0"),
            ("detalles_venta", "unit_con_iva_efectivo REAL DEFAULT 0"),
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
            try:
                self.cursor.execute("UPDATE productos SET sku=NULL WHERE sku=''")
            except Exception:
                logger.exception("No fue posible normalizar SKUs vacíos a NULL")
            self.cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_productos_sku ON productos(sku)"
            )
            self.cursor.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_productos_sku_unico ON productos(sku) WHERE sku IS NOT NULL AND sku <> ''"
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
    ):
        """Insert a new vendor.

        ``commit`` can be set to ``False`` when called inside an existing
        transaction to avoid committing after each insertion.

        When ``Distribuidor_id`` is provided the vendor is treated as a
        supplier and no entry is created in ``trabajadores``.
        """
        if codigo is None:
            codigo = self.get_next_vendedor_codigo()

        if Distribuidor_id is None:
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
                """
                INSERT INTO vendedores (id, codigo, nombre, dui, descripcion, Distribuidor_id)
                VALUES (?, ?, ?, ?, ?, NULL)
                """,
                (trabajador_id, codigo, nombre, dui, descripcion),
            )
        else:
            self.cursor.execute(
                """
                INSERT INTO vendedores (codigo, nombre, dui, descripcion, Distribuidor_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                (codigo, nombre, dui, descripcion, Distribuidor_id),
            )
        if commit:
            self.conn.commit()

    def get_vendedores(self):
        self.cursor.execute("SELECT * FROM vendedores")
        return [dict(row) for row in self.cursor.fetchall()]

    def get_vendedores_distribuidores(self):
        self.cursor.execute(
            "SELECT * FROM vendedores WHERE Distribuidor_id IS NOT NULL"
        )
        return [dict(row) for row in self.cursor.fetchall()]

    def update_vendedor(self, id, codigo, nombre, descripcion, Distribuidor_id, dui=None):
        try:
            self.cursor.execute(
                "UPDATE vendedores SET codigo=?, nombre=?, dui=?, descripcion=?, Distribuidor_id=? WHERE id=?",
                (codigo, nombre, dui, descripcion, Distribuidor_id, id),

            )
            self.cursor.execute(
                "SELECT 1 FROM trabajadores WHERE id=?",
                (id,),
            )
            if self.cursor.fetchone():
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
            self.cursor.execute(
                "SELECT 1 FROM trabajadores WHERE id=?",
                (id,),
            )
            if self.cursor.fetchone():
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
        sku = _normalize_sku_value(sku)
        if isinstance(codigo, str):
            codigo = codigo.strip()
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
        sku = _normalize_sku_value(sku)
        if isinstance(codigo, str):
            codigo = codigo.strip()
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
        with self.lock:
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
            if isinstance(extra, str):
                raise TypeError(
                    "extra for ventas_credito_fiscal must be a mapping or list,"
                    " not a serialized JSON string"
                )
            extra_json = json.dumps(extra) if extra is not None else None
            cols = ["fecha", "total", "cliente_id", "estado", "sincronizada"]
            vals = [fecha, total, cliente_id, estado, 1]
            if Distribuidor_id is not None:
                cols.append("Distribuidor_id")
                vals.append(Distribuidor_id)
            if vendedor_id is not None:
                cols.append("vendedor_id")
                vals.append(vendedor_id)
            if extra_json is not None:
                cols.append("extra")
                vals.append(extra_json)
            placeholders = ", ".join(["?"] * len(vals))
            q = f"INSERT INTO ventas ({', '.join(cols)}) VALUES ({placeholders})"
            with self.lock:
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

    @staticmethod
    def _normalize_date_param(value: Any) -> str | None:
        """Return ``value`` as an ISO formatted date string if possible."""

        if isinstance(value, date):
            return value.isoformat()
        if value is None:
            return None
        return str(value)

    @staticmethod
    def _build_date_conditions(start: str | None, end: str | None, column: str):
        """Return SQL conditions and parameters for ``DATE(column)`` filtering."""

        conditions: list[str] = []
        params: list[str] = []
        if start:
            conditions.append(f"DATE({column}) >= DATE(?)")
            params.append(start)
        if end:
            conditions.append(f"DATE({column}) <= DATE(?)")
            params.append(end)
        return conditions, params

    def get_sales_statistics(
        self,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
        *,
        top_limit: int = 10,
        low_stock_threshold: int = 5,
    ) -> dict[str, Any]:
        """Compute aggregated statistics for synchronized sales."""

        start = self._normalize_date_param(start_date)
        end = self._normalize_date_param(end_date)
        conditions, params = self._build_date_conditions(start, end, "ventas.fecha")
        if self._has_column("ventas", "sincronizada"):
            conditions.append("COALESCE(ventas.sincronizada, 1)=1")
        base_conditions = tuple(conditions)
        base_params = tuple(params)

        def make_clause(extra_conditions: list[str] | None = None) -> str:
            parts = list(base_conditions)
            if extra_conditions:
                parts.extend(extra_conditions)
            if parts:
                return "WHERE " + " AND ".join(parts)
            return ""

        def make_params(extra_params: list[Any] | None = None) -> tuple[Any, ...]:
            values = list(base_params)
            if extra_params:
                values.extend(extra_params)
            return tuple(values)

        summary: dict[str, Any] = {
            "total_sales": 0.0,
            "total_transactions": 0,
            "average_ticket": 0.0,
            "total_costs": 0.0,
            "gross_margin": 0.0,
        }
        periods: dict[str, list[dict[str, Any]]] = {
            "daily": [],
            "monthly": [],
            "yearly": [],
        }
        top_products: list[dict[str, Any]] = []
        sales_by_channel: list[dict[str, Any]] = []
        critical_stock: list[dict[str, Any]] = []

        has_purchase_cost = self._has_column("productos", "precio_compra")
        has_stock = self._has_column("productos", "stock")
        has_vendor_fk = self._has_column("ventas", "vendedor_id")
        has_trabajadores = self._has_table("trabajadores")

        purchase_cost_expr = "COALESCE(productos.precio_compra, 0)" if has_purchase_cost else "0"

        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute(
                f"""
                SELECT COUNT(*) AS total_transactions,
                       SUM(COALESCE(ventas.total, 0)) AS total_sales
                FROM ventas
                {make_clause()}
                """,
                make_params(),
            )
            row = cursor.fetchone()
            if row:
                total_sales = float(row["total_sales"] or 0)
                transactions = int(row["total_transactions"] or 0)
                summary["total_sales"] = total_sales
                summary["total_transactions"] = transactions
                summary["average_ticket"] = (
                    total_sales / transactions if transactions else 0.0
                )

            try:
                cursor.execute(
                    f"""
                    SELECT
                        SUM(COALESCE(detalles_venta.precio_unitario, 0) * COALESCE(detalles_venta.cantidad, 0)) AS ingresos,
                        SUM({purchase_cost_expr} * COALESCE(detalles_venta.cantidad, 0)) AS costos
                    FROM detalles_venta
                    JOIN ventas ON ventas.id = detalles_venta.venta_id
                    LEFT JOIN productos ON productos.id = detalles_venta.producto_id
                    {make_clause()}
                    """,
                    make_params(),
                )
                margin_row = cursor.fetchone()
            except sqlite3.OperationalError:
                margin_row = None
            if margin_row:
                total_costs = float(margin_row["costos"] or 0)
                total_revenue = float(margin_row["ingresos"] or 0)
                summary["total_costs"] = total_costs
                summary["gross_margin"] = total_revenue - total_costs

            period_specs = {
                "daily": ("%Y-%m-%d", 30),
                "monthly": ("%Y-%m", 24),
                "yearly": ("%Y", 10),
            }
            for key, (pattern, limit) in period_specs.items():
                cursor.execute(
                    f"""
                    SELECT strftime('{pattern}', ventas.fecha) AS periodo,
                           COUNT(*) AS total_transacciones,
                           SUM(COALESCE(ventas.total, 0)) AS total_ventas
                    FROM ventas
                    {make_clause()}
                    GROUP BY periodo
                    ORDER BY periodo DESC
                    LIMIT ?
                    """,
                    make_params([limit]),
                )
                rows = []
                for prow in cursor.fetchall():
                    periodo = prow["periodo"]
                    if periodo is None:
                        continue
                    transactions = int(prow["total_transacciones"] or 0)
                    total_amount = float(prow["total_ventas"] or 0)
                    average_ticket = (
                        total_amount / transactions if transactions else 0.0
                    )
                    rows.append(
                        {
                            "period": periodo,
                            "transactions": transactions,
                            "total": total_amount,
                            "average_ticket": average_ticket,
                        }
                    )
                periods[key] = rows

            try:
                cursor.execute(
                    f"""
                    SELECT
                        COALESCE(productos.nombre, 'Sin nombre') AS nombre,
                        SUM(COALESCE(detalles_venta.cantidad, 0)) AS unidades,
                        SUM(COALESCE(detalles_venta.cantidad, 0) * COALESCE(detalles_venta.precio_unitario, 0)) AS total,
                        SUM(
                            (COALESCE(detalles_venta.precio_unitario, 0) - {purchase_cost_expr})
                            * COALESCE(detalles_venta.cantidad, 0)
                        ) AS margen
                    FROM detalles_venta
                    JOIN ventas ON ventas.id = detalles_venta.venta_id
                    LEFT JOIN productos ON productos.id = detalles_venta.producto_id
                    {make_clause()}
                    GROUP BY COALESCE(detalles_venta.producto_id, productos.id), nombre
                    ORDER BY unidades DESC, total DESC
                    LIMIT ?
                    """,
                    make_params([top_limit]),
                )
                top_products_rows = cursor.fetchall()
            except sqlite3.OperationalError:
                top_products_rows = []
            top_products = [
                {
                    "name": row["nombre"],
                    "units": float(row["unidades"] or 0),
                    "total": float(row["total"] or 0),
                    "margin": float(row["margen"] or 0),
                }
                for row in top_products_rows
            ]

            sales_by_channel = []
            try:
                if has_vendor_fk and has_trabajadores:
                    cursor.execute(
                        f"""
                        SELECT COALESCE(trabajadores.nombre, 'Sin vendedor') AS canal,
                               COUNT(*) AS total_transacciones,
                               SUM(COALESCE(ventas.total, 0)) AS total_ventas
                        FROM ventas
                        LEFT JOIN trabajadores ON trabajadores.id = ventas.vendedor_id
                        {make_clause()}
                        GROUP BY canal
                        ORDER BY total_ventas DESC, canal ASC
                        """,
                        make_params(),
                    )
                elif has_vendor_fk:
                    cursor.execute(
                        f"""
                        SELECT
                            CASE
                                WHEN ventas.vendedor_id IS NULL THEN 'Sin vendedor'
                                ELSE 'ID ' || ventas.vendedor_id
                            END AS canal,
                            COUNT(*) AS total_transacciones,
                            SUM(COALESCE(ventas.total, 0)) AS total_ventas
                        FROM ventas
                        {make_clause()}
                        GROUP BY canal
                        ORDER BY total_ventas DESC, canal ASC
                        """,
                        make_params(),
                    )
                else:
                    cursor.execute(
                        f"""
                        SELECT 'Sin vendedor' AS canal,
                               COUNT(*) AS total_transacciones,
                               SUM(COALESCE(ventas.total, 0)) AS total_ventas
                        FROM ventas
                        {make_clause()}
                        """,
                        make_params(),
                    )
                channel_rows = cursor.fetchall()
            except sqlite3.OperationalError:
                channel_rows = []
            for row in channel_rows:
                transactions_value = int(row["total_transacciones"] or 0)
                total_value = float(row["total_ventas"] or 0)
                sales_by_channel.append(
                    {
                        "channel": row["canal"],
                        "transactions": transactions_value,
                        "total": total_value,
                        "average_ticket": (
                            total_value / transactions_value if transactions_value else 0.0
                        ),
                    }
                )

            critical_stock = []
            if has_stock:
                try:
                    cursor.execute(
                        """
                        SELECT nombre, COALESCE(stock, 0) AS stock
                        FROM productos
                        WHERE stock IS NOT NULL AND stock <= ?
                        ORDER BY stock ASC, nombre ASC
                        LIMIT ?
                        """,
                        (low_stock_threshold, top_limit),
                    )
                    stock_rows = cursor.fetchall()
                except sqlite3.OperationalError:
                    stock_rows = []
                critical_stock = [
                    {"name": row["nombre"], "stock": float(row["stock"] or 0)}
                    for row in stock_rows
                ]

        return {
            "summary": summary,
            "periods": periods,
            "top_products": top_products,
            "sales_by_channel": sales_by_channel,
            "critical_stock": critical_stock,
        }

    def get_venta_by_id(self, venta_id: int):
        """Fetch a single sale by its ID."""
        with self.lock:
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
        with self.lock:
            self.cursor.execute(
                "UPDATE ventas SET estado=? WHERE id=?",
                (estado, venta_id),
            )
            self.conn.commit()

    def get_detalles_venta(self, venta_id):
        """Return sale line items joined with product names."""
        with self.lock:
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
        with self.lock:
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

    def get_snapshot_by_venta(self, venta_id: int | None) -> Snapshot | None:
        """Return the stored snapshot for ``venta_id`` if available."""

        if venta_id is None:
            return None
        self.ensure_column("dte_envios", "codigo_generacion", "TEXT")
        with self.lock:
            self.cursor.execute(
                "SELECT codigo_generacion FROM dte_envios WHERE venta_id=? ORDER BY id DESC LIMIT 1",
                (venta_id,),
            )
            row = self.cursor.fetchone()
        if not row:
            return None
        codigo = row[0] if isinstance(row, tuple) else row["codigo_generacion"]
        codigo = (codigo or "").strip()
        if not codigo:
            return None
        try:
            version_dir = versioned_dte.resolve_version_dir(DTES_DIR, codigo)
        except ValueError:
            return None
        json_path = os.path.join(version_dir, "documento.json")
        if not os.path.exists(json_path):
            return None
        try:
            with open(json_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:
            logger.exception(
                "No se pudo leer snapshot %s para venta %s", codigo, venta_id
            )
            return None
        if not isinstance(data, dict):
            return None
        ident = data.get("identificacion") or {}
        tipo_raw = ident.get("tipoDte")
        if isinstance(tipo_raw, int):
            tipo_doc = f"{tipo_raw:02d}"
        elif isinstance(tipo_raw, str):
            tipo_str = tipo_raw.strip()
            if tipo_str.isdigit() and len(tipo_str) <= 2:
                tipo_doc = f"{int(tipo_str):02d}"
            elif tipo_str:
                tipo_doc = tipo_str
            else:
                tipo_doc = None
        else:
            tipo_doc = None
        fecha = ident.get("fecEmi") or ident.get("fechaEmision")
        return Snapshot(
            uuid=str(codigo).upper(),
            path=json_path,
            tipo_documento=tipo_doc,
            fecha_emision=fecha,
            payload=data,
        )

    def get_compras(self):
        self.cursor.execute("SELECT * FROM compras")
        return [dict(row) for row in self.cursor.fetchall()]

    def get_compra(self, compra_id):
        """Return a single purchase by its identifier or ``None`` if missing."""

        self.cursor.execute("SELECT * FROM compras WHERE id=?", (compra_id,))
        row = self.cursor.fetchone()
        return dict(row) if row else None

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
        """Elimina una venta y restaura el inventario asociado."""

        def _to_python(value):
            if value in (None, ""):
                return None
            if isinstance(value, (bytes, bytearray)):
                try:
                    value = value.decode("utf-8")
                except Exception:
                    return None
            if isinstance(value, str):
                text = value.strip()
                if not text:
                    return None
                try:
                    return json.loads(text)
                except Exception:
                    return None
            return value

        def _gather_lote_entries(data):
            entries = []
            if isinstance(data, dict):
                lote_value = None
                for key in ("lote_id", "loteId", "lote"):
                    candidate = data.get(key)
                    if candidate not in (None, ""):
                        lote_value = candidate
                        break
                if lote_value not in (None, ""):
                    entries.append(
                        {
                            "lote_id": lote_value,
                            "cantidad": data.get("cantidad"),
                            "producto_id": data.get("producto_id"),
                        }
                    )
                for value in data.values():
                    entries.extend(_gather_lote_entries(value))
            elif isinstance(data, list):
                for item in data:
                    entries.extend(_gather_lote_entries(item))
            return entries

        def _to_decimal(value):
            try:
                return Decimal(str(value))
            except Exception:
                return None

        try:
            with self.lock:
                self.cursor.execute(
                    "SELECT producto_id, cantidad, extra FROM detalles_venta WHERE venta_id=?",
                    (id,),
                )
                detalles = [dict(row) for row in self.cursor.fetchall()]

                lotes_a_restaurar: dict[int, dict[str, Decimal | int | None]] = {}
                productos_directos: dict[int, Decimal] = {}
                productos_recalc = set()
                productos_direct = set()

                for detalle in detalles:
                    producto_id = detalle.get("producto_id")
                    if not producto_id:
                        continue
                    cantidad_dec = _to_decimal(detalle.get("cantidad"))
                    if cantidad_dec is None or cantidad_dec <= 0:
                        continue

                    parsed_extra = _to_python(detalle.get("extra"))
                    lote_entries = _gather_lote_entries(parsed_extra) if parsed_extra else []

                    valid_lotes = []
                    for entry in lote_entries:
                        lote_id_raw = entry.get("lote_id") if isinstance(entry, dict) else None
                        try:
                            lote_id = int(lote_id_raw)
                        except (TypeError, ValueError):
                            continue
                        cantidad_entry = _to_decimal(entry.get("cantidad")) if isinstance(entry, dict) else None
                        producto_entry = entry.get("producto_id") if isinstance(entry, dict) else None
                        valid_lotes.append(
                            {
                                "lote_id": lote_id,
                                "cantidad": cantidad_entry,
                                "producto_id": producto_entry or producto_id,
                            }
                        )

                    if valid_lotes and any(item["cantidad"] is None for item in valid_lotes):
                        # Si hay un único lote podemos asumir que toda la cantidad proviene de él.
                        if len(valid_lotes) == 1:
                            valid_lotes[0]["cantidad"] = cantidad_dec
                        else:
                            valid_lotes = [item for item in valid_lotes if item["cantidad"] is not None]

                    if valid_lotes:
                        for lote in valid_lotes:
                            cantidad_lote = lote.get("cantidad")
                            if cantidad_lote is None:
                                cantidad_lote = cantidad_dec
                            if cantidad_lote is None or cantidad_lote <= 0:
                                continue
                            info = lotes_a_restaurar.setdefault(
                                lote["lote_id"],
                                {"cantidad": Decimal("0"), "producto_id": lote.get("producto_id")},
                            )
                            info["cantidad"] = info["cantidad"] + cantidad_lote
                            if not info.get("producto_id"):
                                info["producto_id"] = lote.get("producto_id")
                    else:
                        productos_directos[producto_id] = productos_directos.get(producto_id, Decimal("0")) + cantidad_dec

                for lote_id, data in lotes_a_restaurar.items():
                    cantidad = data.get("cantidad")
                    if cantidad is None or cantidad <= 0:
                        continue
                    producto_id = data.get("producto_id")
                    self.cursor.execute(
                        "UPDATE detalles_compra SET cantidad = COALESCE(cantidad, 0) + ? WHERE id=?",
                        (float(cantidad), lote_id),
                    )
                    if self.cursor.rowcount:
                        if producto_id:
                            productos_recalc.add(producto_id)
                    else:
                        if producto_id:
                            productos_directos[producto_id] = productos_directos.get(producto_id, Decimal("0")) + cantidad

                for producto_id, cantidad in productos_directos.items():
                    if not producto_id or cantidad is None or cantidad <= 0:
                        continue
                    self.cursor.execute(
                        "UPDATE productos SET stock = COALESCE(stock, 0) + ? WHERE id=?",
                        (float(cantidad), producto_id),
                    )
                    productos_direct.add(producto_id)

                productos_recalc.difference_update(productos_direct)
                for producto_id in productos_recalc:
                    if not producto_id:
                        continue
                    self.cursor.execute(
                        "SELECT SUM(cantidad) FROM detalles_compra WHERE producto_id=?",
                        (producto_id,),
                    )
                    total = self.cursor.fetchone()[0]
                    if total is None:
                        continue
                    self.cursor.execute(
                        "UPDATE productos SET stock=? WHERE id=?",
                        (float(total), producto_id),
                    )

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
            return True
        except Exception as e:
            logger.exception("Error al eliminar venta: %s", e)
            try:
                self.conn.rollback()
            except Exception:
                pass
            return False

    def backfill_ventas_extra(self) -> int:
        """Populate ``ventas.extra`` for rows that are missing fiscal totals."""

        with self.lock:
            rows = self.cursor.execute(
                "SELECT id FROM ventas WHERE extra IS NULL OR TRIM(extra) = ''"
            ).fetchall()
        venta_ids = [row["id"] for row in rows]
        updated = 0
        for venta_id in venta_ids:
            detalles = self.get_detalles_venta(venta_id)
            if not detalles:
                continue
            data: dict[str, Any] = {"items": detalles}
            fiscal_row = self.get_venta_credito_fiscal(venta_id)
            if fiscal_row:
                for key in (
                    "sumas",
                    "descuentos",
                    "iva",
                    "subtotal",
                    "ventas_exentas",
                    "ventas_no_sujetas",
                    "no_gravado",
                    "precios_incluyen_iva",
                    "descu_no_suj",
                    "descu_exenta",
                    "descu_gravada",
                    "sub_total_ventas",
                ):
                    if fiscal_row.get(key) is not None:
                        data[key] = fiscal_row[key]
                extra_cf = fiscal_row.get("extra")
                if isinstance(extra_cf, dict):
                    data.setdefault("extra", extra_cf)
            extra = build_fiscal_extra(data)
            if not extra:
                continue
            with self.lock:
                self.cursor.execute(
                    "UPDATE ventas SET extra=? WHERE id=?",
                    (json.dumps(extra), venta_id),
                )
                updated += 1
        if updated:
            with self.lock:
                self.conn.commit()
        return updated

    # CRUD DETALLES_VENTA
    def add_detalle_venta(
        self,
        venta_id,
        producto_id,
        cantidad,
        precio_unitario,
        descuento=0,
        descuento_tipo="",
        iva=0,
        comision=0,
        iva_tipo="",
        tipo_fiscal="",
        extra=None,
        precio_con_iva=0,
        vendedor_id=None,
        desc_con_iva=0,
        base=0,
        total=0,
        unit_con_iva_efectivo=0,
    ):
        try:
            extra_json = json.dumps(extra) if extra else None
            tipo_norm = normalize_tipo_fiscal(tipo_fiscal)
            try:
                iva_value = float(Decimal(str(iva or 0)))
            except Exception:
                iva_value = 0.0
            if tipo_norm != "gravada":
                iva_value = 0.0
            with self.lock:
                self.cursor.execute(
                    """
                    INSERT INTO detalles_venta (
                        venta_id,
                        producto_id,
                        cantidad,
                        precio_unitario,
                        descuento,
                        descuento_tipo,
                        iva,
                        comision,
                        iva_tipo,
                        tipo_fiscal,
                        extra,
                        precio_con_iva,
                        vendedor_id,
                        desc_con_iva,
                        base,
                        total,
                        unit_con_iva_efectivo
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        venta_id,
                        producto_id,
                        cantidad,
                        precio_unitario,
                        descuento,
                        descuento_tipo,
                        iva_value,
                        comision,
                        iva_tipo,
                        tipo_norm,
                        extra_json,
                        precio_con_iva,
                        vendedor_id,
                        desc_con_iva,
                        base,
                        total,
                        unit_con_iva_efectivo,
                    ),
                )
                self.conn.commit()
                return self.cursor.lastrowid
        except Exception as e:
            logger.exception("Error al agregar detalle de venta: %s", e)
            self.conn.rollback()
            raise

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
        codActividad=None,
        nombreComercial=None,
        tipoContribuyente=None,
        razonSocial=None,
        commit: bool = True,
    ):
        if codigo is None:
            codigo = self.get_next_cliente_codigo()
        if (
            not departamento
            or not getattr(departamento, "strip", lambda: "")()
            or not municipio
            or not getattr(municipio, "strip", lambda: "")()
        ):
            departamento = "06"
            municipio = "23"
            direccion = direccion or "San Salvador"
        nit = nit.strip() if isinstance(nit, str) else nit
        nit = nit or None
        if self.nit_exists(nit):
            raise ValueError("El NIT ya existe")
        if razonSocial is None:
            razonSocial = nombreComercial
        extras_json = _serialize_cliente_otros(
            {
                "tipoContribuyente": tipoContribuyente,
                "razonSocial": razonSocial,
            }
        )
        self.cursor.execute(
            """
            INSERT INTO clientes (codigo, nombre, nombreComercial, nrc, nit, dui, giro, codActividad, telefono, email, direccion, departamento, municipio, otros)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                codigo,
                nombre,
                nombreComercial,
                nrc,
                nit,
                dui,
                giro,
                codActividad,
                telefono,
                email,
                direccion,
                departamento,
                municipio,
                extras_json,
            ),
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

    def update_cliente(
        self,
        id,
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
        codActividad=None,
        nombreComercial=None,
        tipoContribuyente=None,
        razonSocial=None,
    ):
        if (
            not departamento
            or not getattr(departamento, "strip", lambda: "")()
            or not municipio
            or not getattr(municipio, "strip", lambda: "")()
        ):
            departamento = "06"
            municipio = "23"
            direccion = direccion or "San Salvador"
        nit = nit.strip() if isinstance(nit, str) else nit
        nit = nit or None
        if self.nit_exists(nit, exclude_id=id):
            raise ValueError("El NIT ya existe")
        if razonSocial is None:
            razonSocial = nombreComercial
        extras_json = _serialize_cliente_otros(
            {
                "tipoContribuyente": tipoContribuyente,
                "razonSocial": razonSocial,
            }
        )
        self.cursor.execute(
            """
            UPDATE clientes SET codigo=?, nombre=?, nombreComercial=?, nrc=?, nit=?, dui=?, giro=?, codActividad=?, telefono=?, email=?, direccion=?, departamento=?, municipio=?, otros=? WHERE id=?
            """,
            (
                codigo,
                nombre,
                nombreComercial,
                nrc,
                nit,
                dui,
                giro,
                codActividad,
                telefono,
                email,
                direccion,
                departamento,
                municipio,
                extras_json,
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
            "SELECT id, codigo, nombre, nombreComercial, nrc, nit, dui, giro, codActividad, telefono, email, direccion, departamento, municipio, otros "
            "FROM clientes"
        )
        params = []
        if search:
            like = f"%{search}%"
            query += (
                " WHERE nombre LIKE ? OR nombreComercial LIKE ? OR codigo LIKE ? OR nit LIKE ? OR nrc LIKE ? "
                "OR dui LIKE ? OR telefono LIKE ? OR email LIKE ?"
            )
            params = [like, like, like, like, like, like, like, like]
        self.cursor.execute(query, params)
        return [_apply_cliente_extras(row) for row in self.cursor.fetchall()]

    def get_cliente(self, cliente_id):
        """Return a single client by id."""
        self.cursor.execute("SELECT * FROM clientes WHERE id=?", (cliente_id,))
        row = self.cursor.fetchone()
        return _apply_cliente_extras(row) if row else None

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
        final_path = os.fspath(ruta)
        destino = self._compute_invoice_destination(tipo, final_path)
        if destino is not None:
            try:
                source_path = Path(final_path)
            except (TypeError, ValueError, OSError):
                source_path = None
            if self._ensure_invoice_files(source_path, destino) or destino.exists():
                final_path = os.fspath(destino)

        # Check if a record with the same file path already exists
        self.cursor.execute(
            "SELECT id FROM facturas_pdf WHERE ruta=?",
            (final_path,),
        )
        row = self.cursor.fetchone()
        if row:
            return row["id"]

        fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.cursor.execute(
            "INSERT INTO facturas_pdf (venta_id, tipo, ruta, fecha_creacion) VALUES (?, ?, ?, ?)",
            (venta_id, tipo, final_path, fecha),
        )
        self.conn.commit()
        return self.cursor.lastrowid

    def update_factura_pdf_path(self, venta_id: int, ruta: os.PathLike | str) -> bool:
        """Actualizar la ruta almacenada de la factura PDF más reciente."""

        canonical_path = os.fspath(ruta)
        self.cursor.execute(
            """
            SELECT id, ruta FROM facturas_pdf
            WHERE venta_id=?
            ORDER BY fecha_creacion DESC
            LIMIT 1
            """,
            (venta_id,),
        )
        row = self.cursor.fetchone()
        if not row:
            return False
        if row["ruta"] == canonical_path:
            return False

        self.cursor.execute(
            "UPDATE facturas_pdf SET ruta=? WHERE id=?",
            (canonical_path, row["id"]),
        )
        self.conn.commit()
        return True

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

    def get_dte_correlativo(self, tipo: str, sucursal: str, punto: str) -> int:
        """Obtiene el correlativo actual para la combinación dada."""
        with self.lock:
            self.cursor.execute(
                "SELECT correlativo FROM dte_correlativos WHERE tipo=? AND sucursal=? AND punto=?",
                (tipo, sucursal, punto),
            )
            row = self.cursor.fetchone()
            return int(row["correlativo"]) if row else 0

    def set_dte_correlativo(
        self, tipo: str, sucursal: str, punto: str, valor: int
    ) -> None:
        """Establece el correlativo para la combinación dada."""
        with self.lock:
            with self.conn:
                self.cursor.execute(
                    "SELECT correlativo FROM dte_correlativos WHERE tipo=? AND sucursal=? AND punto=?",
                    (tipo, sucursal, punto),
                )
                if self.cursor.fetchone():
                    self.cursor.execute(
                        "UPDATE dte_correlativos SET correlativo=? WHERE tipo=? AND sucursal=? AND punto=?",
                        (valor, tipo, sucursal, punto),
                    )
                else:
                    self.cursor.execute(
                        "INSERT INTO dte_correlativos (tipo, sucursal, punto, correlativo) VALUES (?, ?, ?, ?)",
                        (tipo, sucursal, punto, valor),
                    )

    def revert_dte_correlativo(
        self, tipo: str, sucursal: str, punto: str, correlativo: int
    ) -> tuple[bool, str | None]:
        """Revierte el correlativo cuando una emisión fue descartada.

        ``correlativo`` representa el número que se intentó utilizar.  Si el
        correlativo actual en base de datos es mayor, se reduce al valor
        inmediatamente anterior para permitir reutilizar la numeración.  Si el
        correlativo almacenado es menor, no se modifica para evitar avanzar la
        secuencia de manera artificial.

        Returns a tuple ``(exito, motivo)`` donde ``motivo`` describe por qué no
        se pudo revertir (cuando ``exito`` es ``False``).
        """

        objetivo = max(int(correlativo) - 1, 0)
        with self.lock:
            with self.conn:
                self.cursor.execute(
                    "SELECT correlativo FROM dte_correlativos WHERE tipo=? AND sucursal=? AND punto=?",
                    (tipo, sucursal, punto),
                )
                row = self.cursor.fetchone()
                if not row:
                    return False, (
                        "No existe un correlativo registrado para la serie "
                        f"tipo {tipo}, sucursal {sucursal}, punto {punto}."
                    )
                actual = int(row["correlativo"])
                if actual < objetivo:
                    return False, (
                        "El correlativo almacenado es {actual} pero se intentó revertir "
                        "el número {correlativo}. La serie parece haber sido ajustada "
                        "manualmente o revertida anteriormente."
                    ).format(actual=actual, correlativo=correlativo)
                if actual == objetivo:
                    # Ya está en el valor deseado, se considera éxito porque no
                    # es necesario aplicar cambios adicionales.
                    return True, None

                logger.info(
                    "Revirtiendo correlativo tipo=%s sucursal=%s punto=%s de %s a %s",
                    tipo,
                    sucursal,
                    punto,
                    actual,
                    objetivo,
                )
                self.cursor.execute(
                    "UPDATE dte_correlativos SET correlativo=? WHERE tipo=? AND sucursal=? AND punto=?",
                    (objetivo, tipo, sucursal, punto),
                )
                return True, None

    def next_dte_correlativo(self, tipo: str, sucursal: str, punto: str) -> int:
        """Obtiene y actualiza el correlativo para la combinación dada."""
        logger.debug(
            "next_dte_correlativo llamado tipo=%s sucursal=%s punto=%s",
            tipo,
            sucursal,
            punto,
        )
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
        logger.debug("Correlativo asignado %s", correlativo)
        return correlativo

    def peek_next_dte_correlativo(self, tipo: str, sucursal: str, punto: str) -> int:
        """Devuelve el siguiente correlativo sin persistir cambios."""

        with self.lock:
            self.cursor.execute(
                "SELECT correlativo FROM dte_correlativos WHERE tipo=? AND sucursal=? AND punto=?",
                (tipo, sucursal, punto),
            )
            row = self.cursor.fetchone()
        if row is None:
            return 1
        try:
            current = int(row["correlativo"])
        except (TypeError, ValueError, KeyError):
            current = int(row[0])
        return current + 1

    def add_dte_pendiente(self, venta_id, dte_json, modo):
        """Registra un DTE pendiente de transmisión a Hacienda."""
        fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.cursor.execute(
            "INSERT INTO dte_pendientes (venta_id, dte_json, modo, fecha_creacion) VALUES (?, ?, ?, ?)",
            (venta_id, stable_stringify(dte_json), modo, fecha),
        )
        self.conn.commit()
        return self.cursor.lastrowid

    def get_dte_pendientes(self):
        """Devuelve la lista de DTE pendientes de transmitir."""
        self.cursor.execute("SELECT * FROM dte_pendientes WHERE transmitido=0")
        rows = [dict(row) for row in self.cursor.fetchall()]
        for r in rows:
            try:
                r["dte_json"] = json.loads(r["dte_json"], parse_float=Decimal)
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

    def update_compra_detallada(self, compra_id, data, detalles):
        with self.lock:
            self.cursor.execute(
                "SELECT producto_id, cantidad FROM detalles_compra WHERE compra_id=?",
                (compra_id,),
            )
            prev_detalles = [dict(row) for row in self.cursor.fetchall()]
            for detalle in prev_detalles:
                producto_id = detalle.get("producto_id")
                cantidad = detalle.get("cantidad", 0) or 0
                if producto_id:
                    self.cursor.execute(
                        "UPDATE productos SET stock = stock - ? WHERE id = ?",
                        (cantidad, producto_id),
                    )

            self.cursor.execute("DELETE FROM detalles_compra WHERE compra_id=?", (compra_id,))

            self.cursor.execute(
                """
                UPDATE compras
                SET fecha=?, producto_id=?, cantidad=?, precio_unitario=?, total=?, Distribuidor_id=?, comision_pct=?, comision_monto=?, vendedor_id=?
                WHERE id=?
                """,
                (
                    data.get("fecha", ""),
                    data.get("producto_id"),
                    data.get("cantidad", 0),
                    data.get("precio_unitario", 0),
                    data.get("total", 0),
                    data.get("Distribuidor_id"),
                    data.get("comision_pct", 0),
                    data.get("comision_monto", 0),
                    data.get("vendedor_id"),
                    compra_id,
                ),
            )

            for detalle in detalles:
                producto_id = detalle.get("producto_id")
                self.add_detalle_compra(
                    compra_id,
                    producto_id,
                    detalle.get("cantidad", 0),
                    detalle.get("precio", 0),
                    detalle.get("fecha_vencimiento", ""),
                    detalle.get("descuento_monto", 0),
                    detalle.get("descuento_tipo", "%"),
                    detalle.get("iva", 0),
                    detalle.get("iva_tipo", ""),
                    detalle.get("comision_pct", 0),
                    detalle.get("comision_monto", 0),
                    detalle.get("comision_tipo", ""),
                    codigo_lote=detalle.get("codigo_lote", ""),
                    registro_sanitario=detalle.get("registro_sanitario", ""),
                    commit=False,
                )
                if producto_id:
                    self.cursor.execute(
                        "UPDATE productos SET stock = stock + ? WHERE id = ?",
                        (detalle.get("cantidad", 0) or 0, producto_id),
                    )

            self.conn.commit()

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
        codigo_lote="",
        registro_sanitario="",
        commit: bool = True,
    ):
        self.cursor.execute("""
            INSERT INTO detalles_compra (
                compra_id, producto_id, cantidad, precio_unitario, fecha_vencimiento,
                codigo_lote, registro_sanitario, descuento, descuento_tipo, iva, iva_tipo, comision_pct, comision_monto, comision_tipo
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            compra_id, producto_id, cantidad, precio_unitario, fecha_vencimiento,
            codigo_lote, registro_sanitario, descuento, descuento_tipo, iva, iva_tipo, comision_pct, comision_monto, comision_tipo
        ))
        if commit:
            self.conn.commit()


    def update_detalle_compra(
        self,
        detalle_id: int,
        *,
        cantidad: Optional[int] = None,
        codigo_lote: Optional[str] = None,
        registro_sanitario: Optional[str] = None,
        fecha_vencimiento: Optional[str] = None,
    ) -> None:
        """Actualiza los datos de un detalle de compra.

        Args:
            detalle_id: Identificador del registro en ``detalles_compra``.
            cantidad: Nueva cantidad del lote. Si es ``None`` no se modifica.
            codigo_lote: Código del lote. Si es ``None`` no se modifica.
            fecha_vencimiento: Fecha de vencimiento en formato ISO
                (``YYYY-MM-DD``).  Si es ``None`` no se modifica y si es una
                cadena vacía se limpia el valor almacenado.

        Raises:
            ValueError: Si el lote no existe, la cantidad es inválida o la
                fecha no puede interpretarse.
        """

        if detalle_id is None:
            raise ValueError("El lote seleccionado no existe.")

        if cantidad is None and codigo_lote is None and fecha_vencimiento is None:
            return

        updates: list[str] = []
        params: list[Any] = []
        requiere_actualizar_stock = False

        if cantidad is not None:
            if cantidad < 0:
                raise ValueError("La cantidad no puede ser negativa.")
            updates.append("cantidad=?")
            params.append(cantidad)
            requiere_actualizar_stock = True

        if codigo_lote is not None:
            updates.append("codigo_lote=?")
            params.append(codigo_lote)

        if registro_sanitario is not None:
            updates.append("registro_sanitario=?")
            params.append(registro_sanitario)

        if fecha_vencimiento is not None:
            normalizada = normalizar_fecha_iso(fecha_vencimiento)
            if fecha_vencimiento and not normalizada:
                raise ValueError("La fecha de vencimiento no es válida.")
            updates.append("fecha_vencimiento=?")
            params.append(normalizada)

        if not updates:
            return

        with self.lock:
            row = self.cursor.execute(
                "SELECT producto_id FROM detalles_compra WHERE id=?",
                (detalle_id,),
            ).fetchone()

            if row is None:
                raise ValueError("El lote seleccionado no existe.")

            producto_id = row["producto_id"]

            params.append(detalle_id)
            self.cursor.execute(
                f"UPDATE detalles_compra SET {', '.join(updates)} WHERE id=?",
                params,
            )

            if requiere_actualizar_stock and producto_id:
                total_row = self.cursor.execute(
                    "SELECT COALESCE(SUM(cantidad), 0) AS total FROM detalles_compra WHERE producto_id=?",
                    (producto_id,),
                ).fetchone()
                total = total_row["total"] if total_row else 0
                self.cursor.execute(
                    "UPDATE productos SET stock=? WHERE id=?",
                    (total, producto_id),
                )

            self.conn.commit()


    def update_detalle_compra_cantidad(self, detalle_id: int, nueva_cantidad: int) -> None:
        """Actualiza la cantidad de un detalle de compra y sincroniza el stock.

        Args:
            detalle_id: Identificador del registro en ``detalles_compra``.
            nueva_cantidad: Cantidad que tendrá el lote después de la edición.

        Raises:
            ValueError: Si el lote no existe o la cantidad es negativa.
        """

        if nueva_cantidad is None:
            raise ValueError("La cantidad no es válida.")

        self.update_detalle_compra(detalle_id, cantidad=nueva_cantidad)


    def delete_detalle_compra(self, detalle_id: int) -> None:
        """Elimina un lote de compra y ajusta el stock y totales asociados."""

        if detalle_id is None:
            raise ValueError("El lote seleccionado no existe.")

        with self.lock:
            detalle = self.cursor.execute(
                """
                SELECT compra_id, producto_id, cantidad, precio_unitario, descuento,
                       iva, iva_tipo, comision_monto, comision_tipo
                FROM detalles_compra
                WHERE id=?
                """,
                (detalle_id,),
            ).fetchone()

            if detalle is None:
                raise ValueError("El lote seleccionado no existe.")

            compra_id = detalle["compra_id"]
            producto_id = detalle["producto_id"]
            cantidad = detalle["cantidad"] or 0

            try:
                if producto_id:
                    self.cursor.execute(
                        "UPDATE productos SET stock = stock - ? WHERE id = ?",
                        (cantidad, producto_id),
                    )

                self.cursor.execute(
                    "DELETE FROM detalles_compra WHERE id=?",
                    (detalle_id,),
                )

                if compra_id:
                    self._recalculate_compra_totals(compra_id)

                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise

    def delete_compra(self, compra_id: int) -> None:
        """Elimina una compra y revierte sus movimientos de inventario."""

        if compra_id is None:
            raise ValueError("La compra seleccionada no existe.")

        with self.lock:
            existe = self.cursor.execute(
                "SELECT 1 FROM compras WHERE id=?",
                (compra_id,),
            ).fetchone()
            if existe is None:
                raise ValueError("La compra seleccionada no existe.")

            detalles = [
                dict(row)
                for row in self.cursor.execute(
                    "SELECT producto_id, cantidad FROM detalles_compra WHERE compra_id=?",
                    (compra_id,),
                ).fetchall()
            ]

            try:
                for detalle in detalles:
                    producto_id = detalle.get("producto_id")
                    cantidad = detalle.get("cantidad", 0) or 0
                    if producto_id:
                        self.cursor.execute(
                            "UPDATE productos SET stock = stock - ? WHERE id = ?",
                            (cantidad, producto_id),
                        )

                self.cursor.execute(
                    "DELETE FROM detalles_compra WHERE compra_id=?",
                    (compra_id,),
                )
                self.cursor.execute(
                    "DELETE FROM compras WHERE id=?",
                    (compra_id,),
                )

                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise

    def _recalculate_compra_totals(self, compra_id: int) -> None:
        """Recalcula el total y la comisión de una compra a partir de sus lotes."""

        detalles = self.cursor.execute(
            """
            SELECT cantidad, precio_unitario, descuento, iva, iva_tipo,
                   comision_monto, comision_tipo
            FROM detalles_compra
            WHERE compra_id=?
            """,
            (compra_id,),
        ).fetchall()

        total = 0.0
        comision_total = 0.0

        for detalle in detalles:
            cantidad = detalle["cantidad"] or 0
            precio = detalle["precio_unitario"] or 0
            descuento = detalle["descuento"] or 0
            iva = detalle["iva"] or 0
            iva_tipo = (detalle["iva_tipo"] or "").strip().lower()
            comision_monto = detalle["comision_monto"] or 0
            comision_tipo = (detalle["comision_tipo"] or "").strip().lower()

            subtotal = max((cantidad * precio) - descuento, 0)
            linea_total = subtotal

            if iva_tipo == "añadido":
                linea_total += iva or 0

            if comision_tipo == "añadida al total":
                linea_total += comision_monto or 0

            total += float(linea_total)
            comision_total += float(comision_monto or 0)

        self.cursor.execute(
            "UPDATE compras SET total=?, comision_monto=? WHERE id=?",
            (total, comision_total, compra_id),
        )


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
        self.ensure_column("ventas", "estado", "TEXT DEFAULT 'Pagada'")
        detalles = data.get("detalles", [])
        total = Decimal("0")
        prepared: list[dict] = []
        for d in detalles:
            cantidad = Decimal(str(d.get("cantidad") or 0))
            precio_iva = Decimal(
                str(
                    d.get("precio_con_iva")
                    or d.get("precio_unit_con_iva")
                    or d.get("precio_unitario")
                    or 0
                )
            )
            descuento = Decimal(
                str(d.get("descuento") or d.get("descuento_valor") or 0)
            )
            descuento_tipo = d.get("descuento_tipo") or "$"
            tipo_fiscal_raw = d.get("tipo_fiscal") or "gravada"
            tipo_fiscal_norm = normalize_tipo_fiscal(tipo_fiscal_raw)
            iva_rate = Decimal("0.13") if tipo_fiscal_norm == "gravada" else Decimal("0")
            calcs = compute_line_totals(
                cantidad,
                precio_iva,
                descuento,
                descuento_tipo,
                iva_rate,
            )
            precio_unitario = d8(calcs["base"] / cantidad) if cantidad else Decimal("0")
            raw_precio_unitario = d.get("precio_unitario")
            if raw_precio_unitario is not None:
                precio_unitario_guardar = d8(Decimal(str(raw_precio_unitario)))
            else:
                precio_unitario_guardar = precio_unitario
            prepared.append(
                {
                    "producto_id": d.get("producto_id"),
                    "cantidad": float(d8(cantidad)),
                    "precio_unitario": float(precio_unitario_guardar),
                    "descuento": float(d8(descuento)),
                    "descuento_tipo": descuento_tipo,
                    "iva": float(calcs["iva"]),
                    "tipo_fiscal": tipo_fiscal_norm,
                    "extra": d.get("extra"),
                    "precio_con_iva": float(d8(precio_iva)),
                    "vendedor_id": d.get("vendedor_id"),
                    "desc_con_iva": float(calcs["desc_con_iva"]),
                    "base": float(calcs["base"]),
                    "total": float(calcs["total_con_iva"]),
                    "unit_con_iva_efectivo": float(calcs["unit_con_iva_efectivo"]),
                }
            )
            total += calcs["total_con_iva"]

        total = d8(total)
        fecha = data.get("fecha", "")
        cliente_id = data.get("cliente_id")
        Distribuidor_id = data.get("Distribuidor_id")
        estado = data.get("estado", "Pagada")
        cols = ["fecha", "total", "estado", "sincronizada"]
        vals = [fecha, float(total), estado, 1]
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

        for d in prepared:
            self.add_detalle_venta(
                venta_id,
                d.get("producto_id"),
                d.get("cantidad"),
                d.get("precio_unitario"),
                d.get("descuento"),
                d.get("descuento_tipo"),
                d.get("iva"),
                d.get("comision", 0),
                d.get("iva_tipo", ""),
                d.get("tipo_fiscal"),
                d.get("extra"),
                d.get("precio_con_iva"),
                d.get("vendedor_id"),
                d.get("desc_con_iva"),
                d.get("base"),
                d.get("total"),
                d.get("unit_con_iva_efectivo"),
            )

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
        """Registra una nota de crédito o débito asociada a una venta.

        Si ``venta_id`` es ``None``, la nota se almacenará sin asociarse a una
        venta. Esto puede ocasionar inconsistencias si la venta no se
        regulariza posteriormente.
        """
        if tipo not in ("credito", "debito", "remision"):
            raise ValueError("tipo debe ser 'credito', 'debito' o 'remision'")

        if venta_id is not None:
            row = self.cursor.execute("SELECT total FROM ventas WHERE id=?", (venta_id,)).fetchone()
            if row is None:
                raise ValueError("La venta indicada no existe")
            if tipo == "credito":
                total_facturado = Decimal(str(row["total"]))
                sum_row = self.cursor.execute(
                    "SELECT COALESCE(SUM(monto),0) AS total FROM notas WHERE venta_id=? AND tipo='credito'",
                    (venta_id,),
                ).fetchone()
                total_creditos = Decimal(str(sum_row["total"]))
                monto_dec = Decimal(str(monto))
                saldo = total_facturado - total_creditos
                if monto_dec > saldo:
                    raise ValueError("El monto de la nota excede el saldo restante de la venta")

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

    def update_nota_detalles(self, nota_id: int, updates: Mapping[str, Any] | None) -> None:
        """Fusiona ``updates`` dentro del JSON ``detalles`` de la nota indicada."""

        if not updates:
            return

        try:
            row = self.cursor.execute(
                "SELECT detalles FROM notas WHERE id=?", (nota_id,)
            ).fetchone()
        except Exception:
            row = None

        current: dict[str, Any] = {}
        if row and row["detalles"]:
            try:
                parsed = json.loads(row["detalles"])
            except Exception:
                parsed = None
            if isinstance(parsed, Mapping):
                current = dict(parsed)

        changed = False
        for key, value in (updates or {}).items():
            if value is None:
                continue
            normalized_key = str(key)
            previous = current.get(normalized_key)
            if isinstance(value, Path):
                value = os.fspath(value)
            if isinstance(value, str):
                candidate = value.strip()
                if not candidate:
                    continue
                value = candidate
            if previous == value:
                continue
            current[normalized_key] = value
            changed = True

        if not changed:
            return

        detalles_json = json.dumps(current, ensure_ascii=False)
        self.cursor.execute(
            "UPDATE notas SET detalles=? WHERE id=?", (detalles_json, nota_id)
        )
        self.conn.commit()

    def find_nota_by_document(
        self,
        *,
        numero_control: str | None = None,
        codigo_generacion: str | None = None,
        json_path: str | None = None,
        tipo: str | None = None,
    ) -> int | None:
        """Ubica el ``id`` de una nota asociada a los identificadores dados."""

        numero = (numero_control or "").strip().upper()
        codigo = (codigo_generacion or "").strip().upper()
        tipo_norm = str(tipo or "").strip().lower() or None

        if codigo or numero:
            try:
                self.ensure_column("dte_envios", "codigo_generacion", "TEXT")
                self.ensure_column("dte_envios", "numero_control", "TEXT")
            except Exception:
                pass
            clauses: list[str] = []
            params: list[Any] = []
            if codigo:
                clauses.append("UPPER(e.codigo_generacion)=?")
                params.append(codigo)
            if numero:
                clauses.append("UPPER(e.numero_control)=?")
                params.append(numero)
            if clauses:
                query = (
                    "SELECT e.venta_id, n.tipo FROM dte_envios AS e "
                    "LEFT JOIN notas AS n ON n.id = e.venta_id "
                    f"WHERE {' OR '.join(clauses)} ORDER BY e.id DESC"
                )
                try:
                    row = self.cursor.execute(query, params).fetchone()
                except Exception:
                    row = None
                if row and row["venta_id"] is not None:
                    nota_tipo = str(row["tipo"] or "").strip().lower()
                    if tipo_norm is None or nota_tipo == tipo_norm:
                        return int(row["venta_id"])

        target_json = None
        if json_path:
            try:
                target_json = os.path.abspath(os.fspath(json_path))
            except (TypeError, ValueError, OSError):
                target_json = None

        try:
            rows = self.cursor.execute(
                "SELECT id, tipo, detalles FROM notas"
            ).fetchall()
        except Exception:
            rows = []

        for row in rows:
            nota_tipo = str(row["tipo"] or "").strip().lower()
            if tipo_norm and nota_tipo != tipo_norm:
                continue
            raw_detalles = row["detalles"]
            detalles: Mapping[str, Any] | None = None
            if raw_detalles:
                try:
                    parsed = json.loads(raw_detalles)
                except Exception:
                    parsed = None
                if isinstance(parsed, Mapping):
                    detalles = parsed
            if not detalles:
                continue
            numero_det = str(detalles.get("numeroControl") or "").strip().upper()
            codigo_det = str(detalles.get("codigoGeneracion") or "").strip().upper()
            if codigo and codigo_det and codigo_det == codigo:
                return int(row["id"])
            if numero and numero_det and numero_det == numero:
                return int(row["id"])
            if target_json:
                stored_json = detalles.get("json_path") or detalles.get("jsonPath")
                if stored_json:
                    try:
                        stored_norm = os.path.abspath(os.fspath(stored_json))
                    except (TypeError, ValueError, OSError):
                        stored_norm = None
                    if stored_norm and stored_norm == target_json:
                        return int(row["id"])

        return None

    def registrar_envio_dte(
        self,
        venta_id,
        modo,
        estado,
        sello,
        respuesta_json="",
        codigo_lote=None,
        codigo_generacion=None,
        numero_control=None,
    ):
        """Guarda un registro del estado de transmisión de un DTE.

        Adicionalmente, preserva un ``estado_ui`` estable calculado en
        función de la respuesta de Hacienda y del último registro previo
        del mismo documento.
        """

        self.ensure_column("dte_envios", "respuesta", "TEXT")
        self.ensure_column("dte_envios", "codigo_lote", "TEXT")
        self.ensure_column("dte_envios", "codigo_generacion", "TEXT")
        self.ensure_column("dte_envios", "numero_control", "TEXT")
        self.ensure_column("dte_envios", "estado_ui", "TEXT")
        self.ensure_column("dte_envios", "estado_ui_tag", "TEXT")
        self.ensure_column("dte_envios", "estado_ui_manual", "INTEGER DEFAULT 0")

        try:
            self.cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_envios_codgen_upper ON dte_envios(UPPER(codigo_generacion))"
            )
        except Exception:
            pass
        try:
            self.cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_envios_numctrl_upper ON dte_envios(UPPER(numero_control))"
            )
        except Exception:
            pass

        # Importación tardía para evitar ciclos en tiempo de carga.
        from dte import (  # type: ignore circular
            _map_estado_hacienda,
            _merge_estado_tag,
            _merge_estado_ui,
        )

        logger.info(
            "registrar_envio_dte: inicio venta_id=%s modo=%s estado=%s codigo_generacion=%s numero_control=%s",
            venta_id,
            modo,
            estado,
            codigo_generacion,
            numero_control,
        )

        respuesta_dict: Mapping[str, Any] | None = None
        respuesta_text: str = ""
        if isinstance(respuesta_json, Mapping):
            respuesta_dict = respuesta_json
            try:
                respuesta_text = json.dumps(respuesta_json, ensure_ascii=False)
            except Exception:
                respuesta_text = json.dumps(respuesta_json)
        elif isinstance(respuesta_json, str):
            respuesta_text = respuesta_json
            if respuesta_json.strip():
                try:
                    respuesta_dict = json.loads(respuesta_json)
                except Exception:
                    respuesta_dict = None
        elif respuesta_json is None:
            respuesta_text = ""
        else:
            try:
                respuesta_text = json.dumps(respuesta_json)
            except Exception:
                respuesta_text = str(respuesta_json)

        mapped_estado = _map_estado_hacienda(respuesta_dict)
        new_ui = mapped_estado["ui"]
        logger.info(
            "registrar_envio_dte: respuesta_normalizada ui=%s tag=%s estado_base=%s",
            new_ui,
            mapped_estado.get("tag"),
            mapped_estado.get("raw"),
        )
        if new_ui == "Pendiente":
            estado_base = mapped_estado.get("raw") or str(estado or "").strip().upper()
            if estado_base == "ACEPTADO":
                new_ui = "Aceptado"
            elif estado_base == "RECHAZADO":
                new_ui = "Rechazado"
            elif estado_base in {"TRANSMITIDO", "RECIBIDO", "PROCESADO"}:
                new_ui = "Enviado"

        # Normaliza valores utilizados para consultas
        codigo_generacion_val = (codigo_generacion or "").strip().upper()
        codigo_generacion_upper = codigo_generacion_val or None
        numero_control_val = (numero_control or "").strip().upper()
        numero_control_upper = numero_control_val or None

        prev_ui = None
        prev_tag = None
        prev_manual = False
        row = None
        if codigo_generacion_upper:
            row = self.cursor.execute(
                """
                SELECT estado_ui, estado_ui_tag, estado_ui_manual FROM dte_envios
                WHERE codigo_generacion IS NOT NULL AND codigo_generacion = ?
                ORDER BY estado_ui_manual DESC, id DESC LIMIT 1
                """,
                (codigo_generacion_upper,),
            ).fetchone()
            if row is not None:
                logger.info(
                    "registrar_envio_dte: encontrado estado previo por codigo_generacion=%s -> ui=%s tag=%s manual=%s",
                    codigo_generacion_upper,
                    row["estado_ui"] if isinstance(row, sqlite3.Row) else row[0],
                    row["estado_ui_tag"] if isinstance(row, sqlite3.Row) else row[1],
                    row["estado_ui_manual"] if isinstance(row, sqlite3.Row) else (row[2] if len(row) > 2 else None),
                )
        if (row is None) and numero_control_upper:
            row = self.cursor.execute(
                """
                SELECT estado_ui, estado_ui_tag, estado_ui_manual FROM dte_envios
                WHERE numero_control IS NOT NULL AND numero_control = ?
                ORDER BY estado_ui_manual DESC, id DESC LIMIT 1
                """,
                (numero_control_upper,),
            ).fetchone()
            if row is not None:
                logger.info(
                    "registrar_envio_dte: encontrado estado previo por numero_control=%s -> ui=%s tag=%s manual=%s",
                    numero_control_upper,
                    row["estado_ui"] if isinstance(row, sqlite3.Row) else row[0],
                    row["estado_ui_tag"] if isinstance(row, sqlite3.Row) else row[1],
                    row["estado_ui_manual"] if isinstance(row, sqlite3.Row) else (row[2] if len(row) > 2 else None),
                )
        if (row is None) and (venta_id is not None):
            try:
                venta_id_int = int(venta_id)
            except Exception:
                venta_id_int = venta_id
            row = self.cursor.execute(
                """
                SELECT estado_ui, estado_ui_tag, estado_ui_manual FROM dte_envios
                WHERE venta_id IS NOT NULL AND venta_id = ?
                ORDER BY estado_ui_manual DESC, id DESC LIMIT 1
                """,
                (venta_id_int,),
            ).fetchone()
            if row is not None:
                logger.info(
                    "registrar_envio_dte: encontrado estado previo por venta_id=%s -> ui=%s tag=%s manual=%s",
                    venta_id_int,
                    row["estado_ui"] if isinstance(row, sqlite3.Row) else row[0],
                    row["estado_ui_tag"] if isinstance(row, sqlite3.Row) else row[1],
                    row["estado_ui_manual"] if isinstance(row, sqlite3.Row) else (row[2] if len(row) > 2 else None),
                )
        if row is not None:
            try:
                prev_ui = row["estado_ui"]
            except Exception:
                try:
                    prev_ui = row[0]
                except Exception:
                    prev_ui = None
            try:
                prev_tag = row["estado_ui_tag"]
            except Exception:
                try:
                    prev_tag = row[1]
                except Exception:
                    prev_tag = None
            try:
                prev_manual = bool(row["estado_ui_manual"])
            except Exception:
                try:
                    prev_manual = bool(row[2]) if len(row) > 2 else False
                except Exception:
                    prev_manual = False

        prev_ui_text = str(prev_ui or "").strip()
        prev_tag_text = str(prev_tag or "").strip().lower()
        manual_override = bool(prev_manual and prev_ui_text)

        logger.info(
            "registrar_envio_dte: estado_previo ui=%s tag=%s manual=%s -> override=%s",
            prev_ui_text,
            prev_tag_text,
            prev_manual,
            manual_override,
        )

        if manual_override:
            merged_ui = prev_ui_text
            merged_tag = prev_tag_text
            logger.info(
                "registrar_envio_dte: preservando estado manual ui=%s tag=%s",
                merged_ui,
                merged_tag,
            )
        else:
            merged_ui = _merge_estado_ui(prev_ui_text, new_ui)
            merged_tag = _merge_estado_tag(prev_tag, mapped_estado.get("tag"), merged_ui)
            logger.info(
                "registrar_envio_dte: estado_calculado ui=%s tag=%s",
                merged_ui,
                merged_tag,
            )

        manual_flag = 1 if manual_override else 0

        fecha_hora = datetime.now(timezone.utc).isoformat()
        self.cursor.execute(
            """
            INSERT INTO dte_envios (
                venta_id, modo, estado, sello, fecha_hora,
                respuesta, codigo_lote, codigo_generacion, numero_control, estado_ui, estado_ui_tag, estado_ui_manual
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                venta_id,
                modo,
                estado,
                sello,
                fecha_hora,
                respuesta_text,
                codigo_lote,
                codigo_generacion_upper,
                numero_control_upper,
                merged_ui,
                merged_tag,
                manual_flag,
            ),
        )
        logger.info(
            "registrar_envio_dte: guardado envio venta_id=%s modo=%s manual=%s ui=%s tag=%s",
            venta_id,
            modo,
            manual_flag,
            merged_ui,
            merged_tag,
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

    def update_envio_estado_ui(
        self,
        *,
        venta_id: int | None = None,
        numero_control: str | None = None,
        codigo_generacion: str | None = None,
        estado_ui: str | None = None,
        estado_ui_tag: str | None = None,
    ) -> bool:
        """Actualiza manualmente el estado de un envío registrado."""

        logger.info(
            "update_envio_estado_ui: solicitud venta_id=%s numero_control=%s codigo_generacion=%s estado_ui=%s estado_ui_tag=%s",
            venta_id,
            numero_control,
            codigo_generacion,
            estado_ui,
            estado_ui_tag,
        )

        with self.lock:
            self.ensure_column("dte_envios", "estado_ui", "TEXT")
            self.ensure_column("dte_envios", "estado_ui_tag", "TEXT")
            self.ensure_column("dte_envios", "estado_ui_manual", "INTEGER DEFAULT 0")

            estado_ui_val = estado_ui.strip() if isinstance(estado_ui, str) else estado_ui
            if isinstance(estado_ui_tag, str):
                tag_val = estado_ui_tag.strip().lower() or None
            else:
                tag_val = estado_ui_tag

            codigo_generacion_val = None
            if isinstance(codigo_generacion, str):
                codigo_generacion_val = codigo_generacion.strip().upper() or None

            numero_control_val = None
            if isinstance(numero_control, str):
                numero_control_val = numero_control.strip().upper() or None

            logger.info(
                "update_envio_estado_ui: valores_normalizados venta_id=%s numero_control=%s codigo_generacion=%s estado_ui=%s estado_ui_tag=%s",
                venta_id,
                numero_control_val,
                codigo_generacion_val,
                estado_ui_val,
                tag_val,
            )

            query = None
            params: tuple[Any, ...] = ()
            if codigo_generacion_val:
                query = (
                    "SELECT id FROM dte_envios "
                    "WHERE codigo_generacion IS NOT NULL AND UPPER(codigo_generacion)=UPPER(?) "
                    "ORDER BY id DESC LIMIT 1"
                )
                params = (codigo_generacion_val,)
            elif numero_control_val:
                query = (
                    "SELECT id FROM dte_envios "
                    "WHERE numero_control IS NOT NULL AND UPPER(numero_control)=UPPER(?) "
                    "ORDER BY id DESC LIMIT 1"
                )
                params = (numero_control_val,)
            elif venta_id is not None:
                query = "SELECT id FROM dte_envios WHERE venta_id=? ORDER BY id DESC LIMIT 1"
                params = (venta_id,)
            else:
                return False

            if query:
                logger.info(
                    "update_envio_estado_ui: consulta=%s params=%s",
                    query,
                    params,
                )

            row = self.cursor.execute(query, params).fetchone() if query else None

            if not row:
                # Crear un registro mínimo para almacenar el estado manual.
                logger.info(
                    "update_envio_estado_ui: no existe registro previo, creando uno nuevo",
                )
                insert_data: dict[str, Any] = {
                    "fecha_hora": datetime.now(timezone.utc).isoformat(),
                    "modo": "manual",
                    "estado_ui": estado_ui_val or None,
                    "estado_ui_tag": tag_val,
                    "estado_ui_manual": 1,
                }
                if venta_id is not None:
                    insert_data["venta_id"] = venta_id
                if codigo_generacion_val:
                    insert_data["codigo_generacion"] = codigo_generacion_val
                if numero_control_val:
                    insert_data["numero_control"] = numero_control_val

                columns = ", ".join(insert_data.keys())
                placeholders = ", ".join("?" for _ in insert_data)
                self.cursor.execute(
                    f"INSERT INTO dte_envios ({columns}) VALUES ({placeholders})",
                    tuple(insert_data.values()),
                )
                self.conn.commit()
                logger.info(
                    "update_envio_estado_ui: creado registro manual id=%s datos=%s",
                    self.cursor.lastrowid,
                    insert_data,
                )
                return True

            envio_id = row["id"] if isinstance(row, sqlite3.Row) else row[0]

            self.cursor.execute(
                "UPDATE dte_envios SET estado_ui=?, estado_ui_tag=?, estado_ui_manual=1 WHERE id=?",
                (estado_ui_val or None, tag_val, envio_id),
            )
            self.conn.commit()
            logger.info(
                "update_envio_estado_ui: actualizado registro id=%s estado_ui=%s tag=%s",
                envio_id,
                estado_ui_val,
                tag_val,
            )
        return True

    def get_envio_fecha_emision(self, venta_id):
        """Devuelve la fecha del último envío para ``venta_id`` en formato ``DD/MM/AAAA``."""

        self.ensure_column("dte_envios", "respuesta", "TEXT")
        row = self.cursor.execute(
            "SELECT fecha_hora, respuesta FROM dte_envios WHERE venta_id=? ORDER BY id DESC LIMIT 1",
            (venta_id,),
        ).fetchone()
        if not row:
            return None

        raw_respuesta = row["respuesta"] if isinstance(row, sqlite3.Row) else row[1]
        if raw_respuesta:
            try:
                respuesta = json.loads(raw_respuesta)
            except Exception:
                respuesta = None
            if isinstance(respuesta, dict):
                fh_procesamiento = respuesta.get("fhProcesamiento")
                if not fh_procesamiento:
                    body = respuesta.get("body")
                    if isinstance(body, dict):
                        fh_procesamiento = body.get("fhProcesamiento")
                fecha_envio = fecha_ddmmaaaa(fh_procesamiento)
                if fecha_envio:
                    return fecha_envio

        fecha_hora = row["fecha_hora"] if isinstance(row, sqlite3.Row) else row[0]
        return fecha_ddmmaaaa(fecha_hora)

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

    # ---- Retenciones (CR) -------------------------------------------------

    def insert_retencion_cr(
        self,
        venta_id: int,
        *,
        payload_json: str,
        codigo_generacion: str,
        numero_control: str,
        codigo_generacion_origen: str,
        numero_control_origen: str,
    ) -> int:
        """Insert a new CR row linked to ``venta_id`` returning the new row ID."""

        self._ensure_retenciones_cr_table()
        if self.get_retencion_cr(venta_id):
            raise ValueError(f"Ya existe un CR-07 para la venta {venta_id}")

        def _norm(value: str | None) -> str:
            text = (value or "").strip()
            if not text:
                raise ValueError("Valor requerido para CR")
            return text.upper()

        now = datetime.now(timezone.utc).isoformat()
        with self.lock:
            self.cursor.execute(
                """
                INSERT INTO retenciones_cr (
                    venta_id, payload_json, codigo_generacion, numero_control,
                    codigo_generacion_origen, numero_control_origen,
                    created_at, updated_at, estado
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    venta_id,
                    payload_json,
                    _norm(codigo_generacion),
                    _norm(numero_control),
                    _norm(codigo_generacion_origen),
                    _norm(numero_control_origen),
                    now,
                    now,
                    "PENDIENTE",
                ),
            )
            self.conn.commit()
            return int(self.cursor.lastrowid)

    def get_retencion_cr(self, venta_id: int) -> dict | None:
        """Return CR record for ``venta_id`` if present."""

        self._ensure_retenciones_cr_table()
        row = self.cursor.execute(
            "SELECT * FROM retenciones_cr WHERE venta_id=?", (venta_id,)
        ).fetchone()
        if not row:
            return None
        return dict(row)

    def update_retencion_cr_signature(self, venta_id: int, jws: str) -> None:
        """Persist the signed JWS for ``venta_id``."""

        self._ensure_retenciones_cr_table()
        now = datetime.now(timezone.utc).isoformat()
        with self.lock:
            self.cursor.execute(
                "UPDATE retenciones_cr SET jws=?, updated_at=? WHERE venta_id=?",
                (jws, now, venta_id),
            )
            if self.cursor.rowcount == 0:
                raise ValueError(f"No existe CR para la venta {venta_id}")
            self.conn.commit()

    def update_retencion_cr_response(
        self,
        venta_id: int,
        *,
        estado: str | None,
        sello: str | None,
        respuesta: str | None,
        enviado_en: str | None = None,
    ) -> None:
        """Update CR response metadata after transmission."""

        self._ensure_retenciones_cr_table()

        def _norm_state(value: str | None) -> str | None:
            if not value:
                return None
            return value.strip().upper() or None

        def _norm_sello(value: str | None) -> str | None:
            if not value:
                return None
            return value.strip().upper() or None

        now = datetime.now(timezone.utc).isoformat()
        envio_ts = enviado_en or now
        with self.lock:
            self.cursor.execute(
                """
                UPDATE retenciones_cr
                SET estado=?, sello=?, respuesta=?, enviado_en=?, updated_at=?
                WHERE venta_id=?
                """,
                (
                    _norm_state(estado),
                    _norm_sello(sello),
                    respuesta,
                    envio_ts,
                    now,
                    venta_id,
                ),
            )
            if self.cursor.rowcount == 0:
                raise ValueError(f"No existe CR para la venta {venta_id}")
            self.conn.commit()

    def update_venta_extra(self, venta_id, extra_dict):
        """Actualiza el campo ``extra`` de la venta, fusionando los datos."""
        self.ensure_column("ventas", "extra", "TEXT")
        with self.lock:
            self.cursor.execute("SELECT extra FROM ventas WHERE id=?", (venta_id,))
            row = self.cursor.fetchone()
        current = {}
        if row and row[0]:
            try:
                current = json.loads(row[0])
            except Exception:
                current = {}
        current.update(extra_dict)
        with self.lock:
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
