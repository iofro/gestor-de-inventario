from db import DB
from PyQt5.QtCore import QAbstractTableModel, Qt
from PyQt5.QtGui import QColor
import json
from datetime import datetime, timedelta
import os
import logging
import sqlite3
from decimal import Decimal as D
from paths import DATOS_NEGOCIO_PATH
from utils.stable_json import DecimalEncoder
from utils.line_totals import compute_line_totals
from utils.monto import d8

try:  # Prefer shared app version if available
    from dte import APP_VERSION
except Exception:  # pragma: no cover - fallback when dte isn't importable
    APP_VERSION = "unknown"

from inventory_validator import (
    validate_inventory_json,
    migrate_inventory_json,
)

logger = logging.getLogger(__name__)


class InventoryManagerError(Exception):
    """Errores de dominio del administrador de inventario."""




class InventoryManager:
    def __init__(self, db: DB | None = None, page_size: int = 50):
        self.db = db or DB()
        self.page_size = page_size
        self.current_page = 0
        self._filter_vendedor_id = None
        self._filter_Distribuidor_id = None
        self._filter_search = ""
        self._model = None
        self.refresh_data()

    def refresh_data(self):
        self._vendedores = self.db.get_vendedores()
        self._Distribuidores = self.db.get_Distribuidores()
        self._vendedores_by_id = {vend["id"]: vend["nombre"] for vend in self._vendedores}
        self._Distribuidores_by_id = {dist["id"]: dist["nombre"] for dist in self._Distribuidores}
        self._products = self.db.get_productos(
            vendedor_id=self._filter_vendedor_id,
            Distribuidor_id=self._filter_Distribuidor_id,
            search=self._filter_search,
        )

        self._clientes = self.db.get_clientes()
        self.load_page(self.current_page)

    def load_page(self, page: int):
        start = page * self.page_size
        end = start + self.page_size
        page_data = self._products[start:end]
        if self._model is None:
            self._model = ProductTableModel(page_data, self._vendedores, self._Distribuidores)
        else:
            self._model.update_data(page_data)
        self.current_page = page


    def get_vendedor_names(self):
        return [vend["nombre"] for vend in self._vendedores]

    def get_Distribuidor_names(self):
        return [dist["nombre"] for dist in self._Distribuidores]

    def get_vendedores(self):
        return self._vendedores

    def get_Distribuidores(self):
        return self._Distribuidores

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
    ):
        self.db.add_producto(
            nombre,
            codigo,
            sku,
            vendedor_id,
            Distribuidor_id,
            precio_compra,
            precio_venta_minorista,
            precio_venta_mayorista,
            stock,
        )
        self.refresh_data()

    def edit_producto(
        self,
        producto_id,
        nombre,
        codigo,
        sku,
        vendedor_id,
        Distribuidor_id,
        precio_compra,
        precio_venta_minorista,
        precio_venta_mayorista,
        stock,
    ):
        self.db.edit_producto(
            producto_id,
            nombre,
            codigo,
            sku,
            vendedor_id,
            Distribuidor_id,
            precio_compra,
            precio_venta_minorista,
            precio_venta_mayorista,
            stock,
        )
        self.refresh_data()

    def delete_producto(self, producto_id):
        self.db.delete_producto(producto_id)
        self.refresh_data()

    def filter_products(self, vendedor_id=None, Distribuidor_id=None, search=""):
        changed = False
        if vendedor_id != self._filter_vendedor_id:
            self._filter_vendedor_id = vendedor_id
            changed = True
        if Distribuidor_id != self._filter_Distribuidor_id:
            self._filter_Distribuidor_id = Distribuidor_id
            changed = True
        if search != self._filter_search:
            self._filter_search = search
            changed = True
        if changed:
            self._apply_filters()

    def _apply_filters(self):
        self._products = self.db.get_productos(
            vendedor_id=self._filter_vendedor_id,
            Distribuidor_id=self._filter_Distribuidor_id,
            search=self._filter_search,
        )
        self.load_page(0)

    @property
    def filter_vendedor_id(self):
        return self._filter_vendedor_id

    @filter_vendedor_id.setter
    def filter_vendedor_id(self, value):
        if value != self._filter_vendedor_id:
            self._filter_vendedor_id = value
            self._apply_filters()

    @property
    def filter_Distribuidor_id(self):
        return self._filter_Distribuidor_id

    @filter_Distribuidor_id.setter
    def filter_Distribuidor_id(self, value):
        if value != self._filter_Distribuidor_id:
            self._filter_Distribuidor_id = value
            self._apply_filters()

    @property
    def filter_search(self):
        return self._filter_search

    @filter_search.setter
    def filter_search(self, value):
        if value != self._filter_search:
            self._filter_search = value
            self._apply_filters()

    def get_products_model(self):
        return self._model

    def get_vendedor_id_by_name(self, nombre):
        for vid, vname in self._vendedores_by_id.items():
            if vname == nombre:
                return vid
        return None

    def get_Distribuidor_id_by_name(self, nombre):
        for did, dname in self._Distribuidores_by_id.items():
            if dname == nombre:
                return did
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

        def write_kv(key, value):
            nonlocal first_section
            if not first_section:
                f.write(",\n")
            json.dump(key, f)
            f.write(":")
            json.dump(value, f, ensure_ascii=False, cls=DecimalEncoder)
            first_section = False

        def write_array(key, iterator):
            nonlocal first_section
            if not first_section:
                f.write(",\n")
            f.write(f'"{key}":[')
            first_item = True
            for item in iterator:
                if not first_item:
                    f.write(",")
                try:
                    json.dump(item, f, ensure_ascii=False)
                except TypeError:
                    f.write(
                        json.dumps(item, ensure_ascii=False, cls=DecimalEncoder)
                    )
                except Exception:
                    raise
                first_item = False
            f.write("]")
            first_section = False

        try:
            with open(filename, "w", encoding="utf-8") as f:
                first_section = True
                f.write("{")
                write_kv("schemaVersion", 1)
                write_kv("generatedAt", datetime.utcnow().isoformat())
                write_kv("appVersion", APP_VERSION)
                write_array("productos", self._products)
                write_array("vendedores", (dict(v) for v in self._vendedores))
                write_array("Distribuidores", (dict(v) for v in self._Distribuidores))
                write_array("clientes", (dict(c) for c in self._clientes))
                # Export only synchronized sales.  Older installations might lack the
                # ``sincronizada`` column, so ensure it exists with a sensible
                # default before querying.
                self.db.ensure_column("ventas", "sincronizada", "INTEGER DEFAULT 1")
                write_array(
                    "ventas",
                    (
                        dict(v)
                        for v in self.db.cursor.execute(
                            "SELECT * FROM ventas WHERE sincronizada=1"
                        )
                    ),
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
                write_array(
                    "dte_envios",
                    (dict(d) for d in self.db.cursor.execute("SELECT * FROM dte_envios")),
                )
                write_array(
                    "notas",
                    (dict(n) for n in self.db.cursor.execute("SELECT * FROM notas")),
                )
                write_array(
                    "facturas_pdf",
                    (dict(f) for f in self.db.cursor.execute("SELECT * FROM facturas_pdf")),
                )
                write_array(
                    "tickets_pdf",
                    (dict(t) for t in self.db.cursor.execute("SELECT * FROM tickets_pdf")),
                )
                if datos_negocio:
                    f.write(",\n\"datos_negocio\":")
                    try:
                        json.dump(datos_negocio, f, ensure_ascii=False)
                    except TypeError:
                        f.write(
                            json.dumps(
                                datos_negocio, ensure_ascii=False, cls=DecimalEncoder
                            )
                        )
                    except Exception:
                        raise
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
                    try:
                        json.dump(tab_order, f, ensure_ascii=False)
                    except TypeError:
                        f.write(
                            json.dumps(tab_order, ensure_ascii=False, cls=DecimalEncoder)
                        )
                    except Exception:
                        raise
                f.write("}")
        except Exception as e:
            logger.exception("Error al exportar inventario a %s", filename)
            try:
                os.remove(filename)
            except OSError:
                pass
            raise InventoryManagerError(
                f"No se pudo exportar inventario a {filename}: {e}"
            ) from e

    def importar_inventario_json(self, filename, *, dry_run: bool = False, strict: bool = True):
        with open(filename, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError as e:
                raise InventoryManagerError(
                    f"No se pudo importar inventario desde {filename}: JSON malformado en línea {e.lineno}, columna {e.colno}"
                ) from e

        data, migrations_applied = migrate_inventory_json(data)
        issues = validate_inventory_json(data)
        errors = [i for i in issues if i["severity"] == "error"]
        warnings = [i for i in issues if i["severity"] == "warning"]

        if strict and errors:
            sample = "; ".join(f"{i['path']}: {i['message']}" for i in errors[:20])
            raise ValueError(
                f"Se encontraron {len(errors)} errores al importar {filename}: {sample}"
            )

        if dry_run:
            return {
                "errors": errors,
                "warnings": warnings,
                "migrations_applied": migrations_applied,
            }

        log_dir = os.path.join("logs")
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(
            log_dir, f"import_inventory_{datetime.now():%Y%m%d_%H%M%S}.log"
        )
        handler = logging.FileHandler(log_path, encoding="utf-8")
        logger.addHandler(handler)
        try:
            self._importar_inventario_json_legacy(data)
        except Exception as e:
            logger.exception("Error al importar inventario desde %s", filename)
            raise InventoryManagerError(
                f"No se pudo importar inventario desde {filename}: {e}"
            ) from e
        finally:
            logger.removeHandler(handler)
            handler.close()

        return data

    def _importar_inventario_json_legacy(self, data):
        # Limpia tablas hijas primero para evitar violaciones de clave foránea
        self.db.conn.execute("BEGIN")
        try:
            self.db.cursor.execute("DELETE FROM detalles_venta")
            self.db.cursor.execute("DELETE FROM ventas_credito_fiscal")
            self.db.cursor.execute("DELETE FROM dte_envios")
            self.db.cursor.execute("DELETE FROM notas")
            self.db.cursor.execute("DELETE FROM facturas_pdf")
            self.db.cursor.execute("DELETE FROM tickets_pdf")
            self.db.cursor.execute("DELETE FROM detalles_compra")
            self.db.cursor.execute("DELETE FROM ventas")
            self.db.cursor.execute("DELETE FROM compras")
            self.db.cursor.execute("DELETE FROM movimientos")
            self.db.cursor.execute("DELETE FROM pagos")
            self.db.cursor.execute("DELETE FROM clientes")
            self.db.cursor.execute("DELETE FROM trabajadores")

            tablas = [
                "detalles_venta",
                "ventas_credito_fiscal",
                "dte_envios",
                "notas",
                "facturas_pdf",
                "tickets_pdf",
                "detalles_compra",
                "ventas",
                "compras",
                "movimientos",
                "pagos",
                "clientes",
                "trabajadores",
            ]
            for tabla in tablas:
                count = self.db.cursor.execute(
                    f"SELECT COUNT(*) FROM {tabla}"
                ).fetchone()[0]
                if count:
                    raise Exception(f"La tabla {tabla} aún contiene registros")

            self.db.conn.commit()
        except Exception:
            self.db.conn.rollback()
            raise

        self.db.limpiar_productos()
        self.db.limpiar_vendedores()
        self.db.limpiar_Distribuidores()

        vendedor_id_map = {}
        Distribuidor_id_map = {}
        producto_id_map = {}
        cliente_id_map = {}
        venta_id_map = {}
        compra_id_map = {}
        trabajador_id_map = {}

        self.db.ensure_column("ventas", "sincronizada", "INTEGER DEFAULT 1")
        self.db.conn.execute("BEGIN")
        try:
            # --- Distribuidores primero ---
            for v in data.get("distribuidores", []):
                self.db.add_Distribuidor_detallado(v, commit=False)
                self.db.cursor.execute(
                    "SELECT id FROM Distribuidores WHERE nombre=? ORDER BY id DESC LIMIT 1",
                    (v["nombre"],),
                )
                new_id = self.db.cursor.fetchone()["id"]
                Distribuidor_id_map[v["id"]] = new_id

            # --- Vendedores después, usando el mapeo correcto ---
            for vend in data.get("vendedores", []):
                dist_id = vend.get("Distribuidor_id")
                new_dist_id = (
                    Distribuidor_id_map.get(dist_id) if dist_id is not None else None
                )
                self.db.add_vendedor(
                    vend["nombre"],
                    vend.get("descripcion", ""),
                    new_dist_id,
                    vend.get("codigo"),
                    vend.get("dui"),
                    commit=False,
                )
                self.db.cursor.execute(
                    "SELECT id FROM vendedores WHERE nombre=? ORDER BY id DESC LIMIT 1",
                    (vend["nombre"],),
                )
                new_id = self.db.cursor.fetchone()["id"]
                vendedor_id_map[vend["id"]] = new_id

            for t in data.get("trabajadores", []):
                codigo = t.get("codigo")
                existing = None
                if codigo:
                    self.db.cursor.execute(
                        "SELECT id FROM trabajadores WHERE codigo=?",
                        (codigo,),
                    )
                    existing = self.db.cursor.fetchone()
                if existing:
                    tid = existing["id"]
                    self.db.cursor.execute(
                        """
                        UPDATE trabajadores SET
                            nombre=?, dui=?, nit=?, fecha_nacimiento=?, cargo=?, area=?, fecha_contratacion=?,
                            telefono=?, email=?, direccion=?, salario_base=?, comentarios=?, es_vendedor=?
                        WHERE id=?
                        """,
                        (
                            t.get("nombre", ""),
                            t.get("dui", ""),
                            t.get("nit", ""),
                            t.get("fecha_nacimiento", ""),
                            t.get("cargo", ""),
                            t.get("area", ""),
                            t.get("fecha_contratacion", ""),
                            t.get("telefono", ""),
                            t.get("email", ""),
                            t.get("direccion", ""),
                            t.get("salario_base", None),
                            t.get("comentarios", ""),
                            1 if t.get("es_vendedor") else 0,
                            tid,
                        ),
                    )
                else:
                    self.db.add_trabajador(t, commit=False)
                    tid = self.db.cursor.lastrowid
                trabajador_id_map[t.get("id")] = tid
                if t.get("es_vendedor"):
                    dist_id = t.get("Distribuidor_id")
                    new_dist_id = (
                        Distribuidor_id_map.get(dist_id)
                        if dist_id is not None
                        else None
                    )
                    self.db.cursor.execute(
                        "SELECT 1 FROM vendedores WHERE id=?",
                        (tid,),
                    )
                    if not self.db.cursor.fetchone():
                        self.db.cursor.execute(
                            "INSERT INTO vendedores (id, codigo, nombre, dui, descripcion, Distribuidor_id) VALUES (?, ?, ?, ?, ?, ?)",
                            (
                                tid,
                                t.get("codigo"),
                                t.get("nombre"),
                                t.get("dui"),
                                t.get("descripcion", ""),
                                new_dist_id,
                            ),
                        )
                    vendedor_id_map[t.get("id")] = tid

            # Productos
            for p in data.get("productos", []):
                old_vend_id = p.get("vendedor_id")
                vend = vendedor_id_map.get(old_vend_id) or trabajador_id_map.get(old_vend_id)
                if old_vend_id and vend is None:
                    logger.warning(
                        "vendedor_id %s not found in mapping, defaulting to None",
                        old_vend_id,
                    )
                dist = Distribuidor_id_map.get(p.get("Distribuidor_id"))
                stock = p.get("stock")
                try:
                    stock = float(stock) if stock is not None else 0
                except (TypeError, ValueError):
                    stock = 0
                self.db.add_producto(
                    p.get("nombre", ""),
                    p.get("codigo", ""),
                    p.get("sku"),
                    vend,
                    dist,
                    p.get("precio_compra", 0),
                    p.get("precio_venta_minorista", 0),
                    p.get("precio_venta_mayorista", 0),
                    stock,
                    commit=False,
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
                    c.get("codigo"),
                    codActividad=c.get("codActividad"),
                    nombreComercial=c.get("nombreComercial"),
                    commit=False,
                )
                self.db.cursor.execute(
                    "SELECT id FROM clientes WHERE nombre=? ORDER BY id DESC LIMIT 1",
                    (c["nombre"],),
                )
                new_id = self.db.cursor.fetchone()["id"]
                cliente_id_map[c["id"]] = new_id

            # Ventas
            for v in data.get("ventas", []):
                # Only import synchronized sales
                if int(v.get("sincronizada", 1)) != 1:
                    continue
                cliente_id = cliente_id_map.get(v.get("cliente_id"))
                Distribuidor_id = Distribuidor_id_map.get(v.get("Distribuidor_id"))
                old_vend_id = v.get("vendedor_id")
                vendedor_id = vendedor_id_map.get(old_vend_id) or trabajador_id_map.get(old_vend_id)
                if old_vend_id and vendedor_id is None:
                    logger.warning(
                        "vendedor_id %s not found in mapping, defaulting to None",
                        old_vend_id,
                    )

                extra = v.get("extra")
                if isinstance(extra, str):
                    try:
                        extra = json.loads(extra)
                    except Exception:
                        pass
                extra_json = json.dumps(extra) if extra is not None else None

                estado = v.get("estado", "Pagada")
                sincronizada = int(v.get("sincronizada", 1))
                self.db.cursor.execute(
                    "INSERT INTO ventas (id, fecha, total, cliente_id, Distribuidor_id, vendedor_id, extra, estado, sincronizada) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        v.get("id"),
                        v.get("fecha", ""),
                        v.get("total", 0),
                        cliente_id,
                        Distribuidor_id,
                        vendedor_id,
                        extra_json,
                        estado,
                        sincronizada,

                    ),
                )
                venta_id_map[v["id"]] = v.get("id")

            # ensure AUTOINCREMENT counters are updated
            max_venta_id = (
                self.db.cursor.execute("SELECT MAX(id) FROM ventas").fetchone()[0] or 0
            )
            self.db.cursor.execute(
                "UPDATE sqlite_sequence SET seq=? WHERE name='ventas'", (max_venta_id,)
            )

            # Compras
            for c in data.get("compras", []):
                Distribuidor_id = (
                    Distribuidor_id_map.get(c.get("Distribuidor_id"))
                    if c.get("Distribuidor_id") is not None
                    else None
                )
                vendedor_id = (
                    vendedor_id_map.get(c.get("vendedor_id"))
                    if c.get("vendedor_id") is not None
                    else None
                )
                comision_pct = c.get("comision_pct", 0)
                comision_monto = c.get("comision_monto", 0)
                self.db.cursor.execute(
                    "INSERT INTO compras (fecha, producto_id, cantidad, precio_unitario, total, Distribuidor_id, comision_pct, comision_monto, vendedor_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        c.get("fecha", ""),
                        None,
                        0,
                        0,
                        c.get("total", 0),
                        Distribuidor_id,
                        comision_pct,
                        comision_monto,
                        vendedor_id,
                    ),
                )
                new_id = self.db.cursor.lastrowid
                compra_id_map[c["id"]] = new_id

            # Detalles de venta
            for d in data.get("detalles_venta", []):
                venta_id = venta_id_map.get(d.get("venta_id"))
                producto_id = producto_id_map.get(d.get("producto_id"))
                vendedor_id = None
                old_vend_id = d.get("vendedor_id")
                if old_vend_id is not None:
                    vendedor_id = vendedor_id_map.get(old_vend_id) or trabajador_id_map.get(old_vend_id)
                    if vendedor_id is None:
                        logger.warning(
                            "detalle_venta vendedor_id %s not found in mapping, defaulting to None",
                            old_vend_id,
                        )
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
                            vendedor_id,
                        ),
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
                        d.get("comision_tipo", ""),
                        commit=False,
                    )

            # Movimientos (opcional, si tienes movimientos)
            for m in data.get("movimientos", []):
                producto_id = producto_id_map.get(m.get("producto_id"))
                self.db.cursor.execute(
                    "INSERT INTO movimientos (fecha, tipo, producto_id, cantidad, motivo, usuario) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        m.get("fecha", ""),
                        m.get("tipo", ""),
                        producto_id,
                        m.get("cantidad", 0),
                        m.get("motivo", ""),
                        m.get("usuario", ""),
                    ),
                )

            for de in data.get("dte_envios", []):
                self.db.cursor.execute(
                    "INSERT INTO dte_envios (venta_id, modo, estado, sello, fecha_hora, respuesta) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        venta_id_map.get(de.get("venta_id")),
                        de.get("modo"),
                        de.get("estado"),
                        de.get("sello"),
                        de.get("fecha_hora"),
                        de.get("respuesta"),
                    ),
                )

            for n in data.get("notas", []):
                self.db.cursor.execute(
                    "INSERT INTO notas (venta_id, tipo, fecha, monto, motivo, detalles) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        venta_id_map.get(n.get("venta_id")),
                        n.get("tipo"),
                        n.get("fecha"),
                        n.get("monto"),
                        n.get("motivo"),
                        n.get("detalles"),
                    ),
                )

            for fp in data.get("facturas_pdf", []):
                self.db.cursor.execute(
                    "INSERT INTO facturas_pdf (venta_id, tipo, ruta, fecha_creacion) VALUES (?, ?, ?, ?)",
                    (
                        venta_id_map.get(fp.get("venta_id")),
                        fp.get("tipo"),
                        fp.get("ruta"),
                        fp.get("fecha_creacion"),
                    ),
                )

            for tp in data.get("tickets_pdf", []):
                self.db.cursor.execute(
                    "INSERT INTO tickets_pdf (venta_id, ruta, fecha_creacion) VALUES (?, ?, ?)",
                    (
                        venta_id_map.get(tp.get("venta_id")),
                        tp.get("ruta"),
                        tp.get("fecha_creacion"),
                    ),
                )

            # Ventas crédito fiscal
            self.db.limpiar_ventas_credito_fiscal()
            self.db.cursor.execute(
                "DELETE FROM sqlite_sequence WHERE name='ventas_credito_fiscal'"
            )
            self.db.conn.commit()
            self.db.conn.execute("BEGIN")
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
        except Exception:
            self.db.conn.rollback()
            raise

        # Remove orphan sales that have no related records
        self.db.limpiar_ventas_huerfanas()

        self.refresh_data()

        datos_path = DATOS_NEGOCIO_PATH
        if "datos_negocio" in data:
            datos_negocio = data.get("datos_negocio")
            if datos_negocio is not None:
                with open(datos_path, "w", encoding="utf-8") as f:
                    json.dump(datos_negocio, f, ensure_ascii=False, indent=2)
            elif os.path.exists(datos_path):
                os.remove(datos_path)

        return data

    def add_Distribuidor(self, nombre):
        self.db.add_Distribuidor(nombre)
        self.refresh_data()

    def add_vendedor(self, nombre, Distribuidor_id=None, codigo=None, dui=None):
        try:
            self.db.add_vendedor(
                nombre,
                descripcion="",
                Distribuidor_id=Distribuidor_id,
                codigo=codigo,
                dui=dui,
            )
        except sqlite3.IntegrityError as exc:
            logger.exception("Error de integridad al agregar vendedor %s", nombre)
            raise InventoryManagerError(
                "No se pudo agregar el vendedor; el registro ya existe o los datos son inválidos."
            ) from exc
        except sqlite3.DatabaseError as exc:
            logger.exception("Error de base de datos al agregar vendedor %s", nombre)
            raise InventoryManagerError(
                "Ocurrió un error de base de datos al agregar el vendedor."
            ) from exc


        self.refresh_data()

    def add_cliente(
        self,
        nombre,
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
        codigo=None,
        nombreComercial=None,
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
            codActividad=codActividad,
            nombreComercial=nombreComercial,
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
        codActividad=None,
        nombreComercial=None,
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
            codActividad=codActividad,
            nombreComercial=nombreComercial,
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
        detalles = []
        total = D("0")
        for item in venta_data.get("detalles", []):
            cantidad = D(str(item.get("cantidad") or 0))
            precio_con_iva = D(
                str(
                    item.get("precio_unit_con_iva")
                    or item.get("precio_con_iva")
                    or item.get("precio_unitario")
                    or 0
                )
            )
            descuento_valor = D(
                str(item.get("descuento_valor") or item.get("descuento") or 0)
            )
            descuento_tipo = item.get("descuento_tipo", "$")
            tipo_fiscal = item.get("tipo_fiscal", "Venta gravada")
            iva_rate = D("0.13") if tipo_fiscal == "Venta gravada" else D("0")
            calcs = compute_line_totals(
                cantidad,
                precio_con_iva,
                descuento_valor,
                descuento_tipo,
                iva_rate,
            )
            detalle = {
                "producto_id": item.get("producto_id"),
                "cantidad": float(d8(cantidad)),
                "precio_unitario": float(d8(calcs["base"] / cantidad)) if cantidad else 0,
                "descuento": float(d8(descuento_valor)),
                "descuento_tipo": descuento_tipo,
                "iva": float(calcs["iva"]),
                "tipo_fiscal": tipo_fiscal,
                "precio_con_iva": float(d8(precio_con_iva)),
                "desc_con_iva": float(calcs["desc_con_iva"]),
                "base": float(calcs["base"]),
                "total": float(calcs["total_con_iva"]),
                "unit_con_iva_efectivo": float(calcs["unit_con_iva_efectivo"]),
            }
            detalles.append(detalle)
            total += calcs["total_con_iva"]
        data = dict(venta_data)
        data["detalles"] = detalles
        data["total"] = float(d8(total))
        self.db.add_venta_detallada(data)
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
                stock = row.get("stock")
                try:
                    stock = float(stock) if stock is not None else 0
                except (TypeError, ValueError):
                    stock = 0
                return stock
            # Si agregas comisión:
            # elif col == 4:
            #     return f"{row.get('comision_base', 0)}%"  # O el campo que corresponda
        elif role == Qt.BackgroundRole and col == 3:
            stock = row.get("stock")
            try:
                stock = float(stock) if stock is not None else 0
            except (TypeError, ValueError):
                stock = 0
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