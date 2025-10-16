from copy import deepcopy
from pathlib import Path
from db import DB
from PyQt5.QtCore import QAbstractTableModel, Qt
from PyQt5.QtGui import QColor
import json
import re
from datetime import datetime, timedelta, time as dt_time
import os
import logging
import sqlite3
from decimal import Decimal as D, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Iterable, List, Mapping
from paths import (
    DATOS_NEGOCIO_PATH,
    DTES_DIR,
    FACTURAS_ARCHIVE_CF_DIR,
    FACTURAS_CONSUMIDOR_FINAL_DIR,
    TICKETS_OUTPUT_DIR,
    ensure_user_dir,
    get_canonical_dte_dir,
    user_logs_path,
)
from utils.stable_json import DecimalEncoder
from utils.fiscal_extra import normalize_tipo_fiscal
from utils.line_totals import compute_line_totals
from utils.monto import d8
from utils.party_resolver import Catalogs, normalize_identifier
from declaracion.anexo_consumidor_final import VentaCF
from declaracion.anexo_xix import DTEAnulado

try:  # Prefer shared app version if available
    from dte import APP_VERSION
except Exception:  # pragma: no cover - fallback when dte isn't importable
    APP_VERSION = "unknown"

from inventory_validator import (
    validate_inventory_json,
    migrate_inventory_json,
)

logger = logging.getLogger(__name__)


_TOKEN_FIELDS = ("token_pruebas", "token_produccion")


_ANEXO_ESTADOS_ACEPTADOS = {"aceptado", "procesado", "recibido", "enviado"}
_PERIODO_FORMAT = re.compile(r"^\d{6}$")


def _map_tipo_anulacion_estado(motivo: Mapping[str, object] | None) -> str | None:
    if not isinstance(motivo, Mapping):
        return None
    raw_tipo = motivo.get("tipoAnulacion")
    try:
        tipo = int(raw_tipo)
    except (TypeError, ValueError):
        return None
    if tipo == 1:
        return "D"
    if tipo == 2:
        return "A"
    if tipo == 3:
        return "X"
    return None


def _metadata_estado_aceptado(metadata: Mapping[str, object] | None) -> bool:
    if not isinstance(metadata, Mapping):
        return False
    respuesta = metadata.get("respuesta")
    if isinstance(respuesta, Mapping):
        for key in ("estado", "estadoEvento", "descripcionEstado"):
            valor = respuesta.get(key)
            if isinstance(valor, str) and valor.strip():
                estado_norm = valor.strip().lower()
                return estado_norm in _ANEXO_ESTADOS_ACEPTADOS
    return False


def _extract_manual_tokens(datos_negocio: dict | None) -> dict:
    if not isinstance(datos_negocio, dict):
        return {}
    dte_api = datos_negocio.get("dte_api")
    if not isinstance(dte_api, dict):
        return {}
    tokens: dict[str, str] = {}
    for field in _TOKEN_FIELDS:
        value = dte_api.get(field)
        if value:
            tokens[field] = value
    return tokens


def _sanitize_datos_negocio(datos_negocio: dict | None) -> dict:
    if not isinstance(datos_negocio, dict):
        return {}
    sanitized = deepcopy(datos_negocio)
    dte_api = sanitized.get("dte_api")
    if isinstance(dte_api, dict):
        for field in _TOKEN_FIELDS:
            dte_api.pop(field, None)
        if not dte_api:
            sanitized.pop("dte_api", None)
    return sanitized


def _iter_cf_candidate_dirs() -> Iterable[Path]:
    """Yield directories that may contain DTE JSON for consumidor final."""

    candidates: list[Path] = []
    try:
        canonical = Path(get_canonical_dte_dir("ConsumidorFinal"))
    except Exception:
        canonical = None
    if canonical is not None:
        candidates.append(canonical)

    for raw_dir in (
        FACTURAS_CONSUMIDOR_FINAL_DIR,
        FACTURAS_ARCHIVE_CF_DIR,
        TICKETS_OUTPUT_DIR,
        DTES_DIR,
    ):
        if not raw_dir:
            continue
        try:
            candidates.append(Path(raw_dir))
        except TypeError:
            continue

    seen_dirs: set[str] = set()

    def _yield_once(path: Path) -> Iterable[Path]:
        norm = os.path.normpath(str(path))
        if norm in seen_dirs:
            return ()
        seen_dirs.add(norm)
        return (path,)

    for base in candidates:
        for candidate in _yield_once(base):
            yield candidate

        base_name = base.name.lower()
        subdir_hints: tuple[str, ...]
        if base_name in {"dtes"}:
            subdir_hints = (
                "fcf",
                "consumidor_final",
                "consumidorfinal",
                "consumidor-final",
                "facturas_consumidor_final",
            )
        elif base_name in {"tickets"}:
            subdir_hints = ("consumidor_final",)
        elif base_name in {"facturas"}:
            subdir_hints = ("consumidor_final",)
        else:
            subdir_hints = ()

        for hint in subdir_hints:
            hinted = base / hint
            for candidate in _yield_once(hinted):
                yield candidate


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
        self._modo_transmision_actual: str | None = None
        self.catalogs: Catalogs = Catalogs(vendors={}, distributors={}, products={}, db=self.db)
        self.refresh_data()

    def refresh_data(self):
        self._vendedores = self.db.get_vendedores()
        self._vendedores_compra = self.db.get_vendedores_distribuidores()
        self._Distribuidores = self.db.get_Distribuidores()
        self._vendedores_by_id = {vend["id"]: vend["nombre"] for vend in self._vendedores}
        self._vendedores_compra_by_id = {
            vend["id"]: vend["nombre"] for vend in self._vendedores_compra
        }
        self._Distribuidores_by_id = {dist["id"]: dist["nombre"] for dist in self._Distribuidores}
        vendor_catalog: dict[int, dict] = {}
        for vend in self._vendedores_compra:
            vid = normalize_identifier(vend.get("id")) if isinstance(vend, Mapping) else None
            if vid is None:
                continue
            vendor_catalog[vid] = dict(vend)
        distributor_catalog: dict[int, dict] = {}
        for dist in self._Distribuidores:
            did = normalize_identifier(dist.get("id")) if isinstance(dist, Mapping) else None
            if did is None:
                continue
            distributor_catalog[did] = dict(dist)
        all_products = self.db.get_productos()
        product_catalog: dict[int, dict] = {}
        for prod in all_products:
            pid = normalize_identifier(prod.get("id")) if isinstance(prod, Mapping) else None
            if pid is None:
                continue
            product_catalog[pid] = dict(prod)
        self.catalogs = Catalogs(
            vendors=vendor_catalog,
            distributors=distributor_catalog,
            products=product_catalog,
            db=self.db,
        )
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


    def set_modo_transmision_actual(self, modo: str | None) -> None:
        """Actualizar el modo de transmisión activo en la interfaz."""

        if modo is None:
            self._modo_transmision_actual = None
            return

        text = str(modo).strip().lower()
        if not text:
            self._modo_transmision_actual = None
        elif text.startswith("2") or "contingencia" in text:
            self._modo_transmision_actual = "contingencia"
        else:
            self._modo_transmision_actual = "normal"


    def get_modo_transmision_actual(self) -> str:
        """Obtener el modo de transmisión activo o el configurado por defecto."""

        if self._modo_transmision_actual:
            return self._modo_transmision_actual

        try:
            from dte import get_default_modo_transmision

            return get_default_modo_transmision()
        except Exception:
            return "normal"


    def get_vendedor_names(self):
        return [vend["nombre"] for vend in self._vendedores]

    def get_Distribuidor_names(self):
        return [dist["nombre"] for dist in self._Distribuidores]

    def get_vendedores(self):
        return self._vendedores

    def get_vendedores_compra(self):
        return self._vendedores_compra

    def get_Distribuidores(self):
        return self._Distribuidores

    def get_anexo_xix_registros(self, periodo: str) -> List[DTEAnulado]:
        periodo_text = str(periodo or "").strip()
        if not _PERIODO_FORMAT.fullmatch(periodo_text):
            return []

        try:
            base_dir = Path(ensure_user_dir("dtes", "actualizaciones", "anulacion"))
        except Exception:
            return []

        if not base_dir.exists():
            return []

        registros: dict[tuple[str, str], DTEAnulado] = {}

        try:
            entries = sorted(base_dir.iterdir())
        except OSError:
            entries = []

        for entry in entries:
            if not entry.is_dir():
                continue

            doc_path = entry / "documento.json"
            if not doc_path.is_file():
                continue

            try:
                with doc_path.open("r", encoding="utf-8") as fh:
                    evento = json.load(fh)
            except Exception:
                continue

            if not isinstance(evento, Mapping):
                continue

            identificacion = evento.get("identificacion")
            if not isinstance(identificacion, Mapping):
                continue

            fec_anula_raw = identificacion.get("fecAnula")
            if fec_anula_raw in (None, ""):
                continue
            fec_anula_text = str(fec_anula_raw).strip()
            if len(fec_anula_text) < 7:
                continue
            periodo_evento = fec_anula_text[:4] + fec_anula_text[5:7]
            if periodo_evento != periodo_text:
                continue

            documento = evento.get("documento")
            if not isinstance(documento, Mapping):
                continue

            numero_control = str(documento.get("numeroControl") or "").strip().upper()
            codigo_dte = str(documento.get("codigoGeneracion") or "").strip().upper()
            sello_recibido = str(documento.get("selloRecibido") or "").strip().upper()
            tipo_doc_raw = documento.get("tipoDte") or documento.get("tipoDocumento")
            tipo_doc = str(tipo_doc_raw or "").strip()
            if tipo_doc.isdigit() and len(tipo_doc) < 2:
                tipo_doc = tipo_doc.zfill(2)

            motivo_value = evento.get("motivo")
            motivo = motivo_value if isinstance(motivo_value, Mapping) else None
            estado_detalle = _map_tipo_anulacion_estado(motivo)

            if not (numero_control and codigo_dte and sello_recibido and tipo_doc and estado_detalle):
                continue

            metadata_path = entry / "metadata.json"
            metadata: Mapping[str, object] | None = None
            if metadata_path.is_file():
                try:
                    with metadata_path.open("r", encoding="utf-8") as fh:
                        loaded_meta = json.load(fh)
                    if isinstance(loaded_meta, Mapping):
                        metadata = loaded_meta
                except Exception:
                    metadata = None

            if not _metadata_estado_aceptado(metadata):
                continue

            key = (numero_control, codigo_dte)
            registros[key] = DTEAnulado(
                numero_control=numero_control,
                tipo_documento=tipo_doc,
                sello_recepcion=sello_recibido,
                codigo_generacion=codigo_dte,
                estado=estado_detalle,
            )

        if not registros:
            return []

        ordered_keys = sorted(registros.keys())
        return [registros[key] for key in ordered_keys]

    def get_anexo_consumidor_final_registros(self, periodo: str) -> List[VentaCF]:
        periodo_text = str(periodo or "").strip()
        if not _PERIODO_FORMAT.fullmatch(periodo_text):
            return []

        year = int(periodo_text[:4])
        month = int(periodo_text[4:])

        def _parse_fecha(value: object) -> datetime | None:
            if value is None:
                return None
            text = str(value).strip()
            if not text:
                return None
            for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y%m%d"):
                try:
                    parsed = datetime.strptime(text[:10], fmt)
                except ValueError:
                    continue
                return parsed
            return None

        def _to_decimal(value: object) -> D:
            if value in (None, "", "null"):
                return D("0")
            if isinstance(value, D):
                return value
            if isinstance(value, (int, float)):
                return D(str(value))
            if isinstance(value, str):
                text = value.strip()
                if not text:
                    return D("0")
                try:
                    return D(text)
                except InvalidOperation:
                    text = text.replace(",", "")
                    try:
                        return D(text)
                    except InvalidOperation:
                        return D("0")
            return D("0")

        def _format_decimal(value: D) -> str:
            quantized = value.quantize(D("0.01"), rounding=ROUND_HALF_UP)
            return f"{quantized:.2f}"

        def _normalize_tipo(value: object) -> str:
            text = str(value or "").strip()
            if not text:
                return "0"
            if text.isdigit():
                return str(int(text)).zfill(1)
            try:
                numeric = int(float(text))
            except (ValueError, TypeError):
                return "0"
            return str(numeric)

        def _normalize_tipo_doc(value: object) -> str:
            text = str(value or "").strip()
            if not text:
                return "01"
            if text.isdigit():
                return f"{int(text):02d}"
            return text

        def _accepted_payload(payload: Mapping[str, object]) -> bool:
            if _metadata_estado_aceptado(payload):
                return True
            sello = payload.get("selloRecibido")
            if isinstance(sello, str) and sello.strip():
                return True
            respuesta = payload.get("respuesta")
            if isinstance(respuesta, Mapping):
                sello_resp = respuesta.get("selloRecibido")
                if isinstance(sello_resp, str) and sello_resp.strip():
                    return True
                for key in ("estado", "estadoEvento", "descripcionEstado"):
                    valor = respuesta.get(key)
                    if isinstance(valor, str) and valor.strip().lower() in _ANEXO_ESTADOS_ACEPTADOS:
                        return True
            return False

        registros: list[tuple[datetime, str, VentaCF]] = []
        seen_codigos: set[str] = set()
        seen_paths: set[str] = set()

        candidate_dirs = [path for path in _iter_cf_candidate_dirs() if path.exists()]
        if not candidate_dirs:
            return []

        for base_dir in candidate_dirs:
            for json_path in sorted(base_dir.rglob("*.json")):
                if any(part.lower() == "copia de seguridad" for part in json_path.parts):
                    continue

                json_norm = os.path.normpath(str(json_path))
                if json_norm in seen_paths:
                    continue
                seen_paths.add(json_norm)

                try:
                    with json_path.open("r", encoding="utf-8") as fh:
                        payload = json.load(fh)
                except Exception:
                    continue

                if not isinstance(payload, Mapping):
                    continue

                dte_payload = payload.get("dteJson") if isinstance(payload, Mapping) else None
                if not isinstance(dte_payload, Mapping):
                    dte_payload = payload.get("dte_json") if isinstance(payload, Mapping) else None
                if not isinstance(dte_payload, Mapping):
                    dte_payload = payload.get("dte") if isinstance(payload, Mapping) else None
                if not isinstance(dte_payload, Mapping):
                    dte_payload = payload
                if not isinstance(dte_payload, Mapping):
                    continue

                ident_raw = dte_payload.get("identificacion") or dte_payload.get("identificador")
                if not isinstance(ident_raw, Mapping):
                    continue

                fecha_dt = _parse_fecha(ident_raw.get("fecEmi"))
                if not fecha_dt or fecha_dt.year != year or fecha_dt.month != month:
                    continue

                tipo_doc = _normalize_tipo_doc(ident_raw.get("tipoDte"))
                if tipo_doc not in {"01", "02", "10", "11"}:
                    continue

                codigo_generacion = str(ident_raw.get("codigoGeneracion") or "").strip()
                if not codigo_generacion:
                    continue
                if codigo_generacion in seen_codigos:
                    continue

                if not _accepted_payload(payload):
                    continue

                numero_control = str(ident_raw.get("numeroControl") or "").strip()

                resumen = dte_payload.get("resumen")
                if not isinstance(resumen, Mapping):
                    resumen = {}

                ventas_exentas = _to_decimal(resumen.get("totalExenta"))
                internas_ns = _to_decimal(resumen.get("totalNoGravado"))
                ventas_no_sujetas = _to_decimal(resumen.get("totalNoSuj"))
                ventas_gravadas = _to_decimal(resumen.get("totalGravada"))
                exp_ca = _to_decimal(
                    resumen.get("totalExportacionCA")
                    or resumen.get("totalExportacionCa")
                    or resumen.get("totalExportacionCentroAmerica")
                )
                exp_fuera = _to_decimal(
                    resumen.get("totalExportacionFueraCA")
                    or resumen.get("totalExportacion")
                )
                exp_servicios = _to_decimal(resumen.get("totalExportacionServicios"))
                zonas_francas = _to_decimal(resumen.get("totalZonasFrancas"))
                terceros_no_domic = _to_decimal(resumen.get("totalTercerosNoDomiciliados"))

                componentes = [
                    ventas_exentas,
                    internas_ns,
                    ventas_no_sujetas,
                    ventas_gravadas,
                    exp_ca,
                    exp_fuera,
                    exp_servicios,
                    zonas_francas,
                    terceros_no_domic,
                ]
                total_componentes = sum(componentes)
                total_operacion = _to_decimal(
                    resumen.get("totalPagar") or resumen.get("montoTotalOperacion")
                )
                if total_operacion == D("0"):
                    total_operacion = total_componentes
                if total_operacion != total_componentes:
                    diferencia = total_operacion - total_componentes
                    ventas_gravadas += diferencia
                    componentes[3] = ventas_gravadas
                    total_componentes = sum(componentes)

                fecha_only = fecha_dt.date()

                registro = VentaCF(
                    fecha=fecha_only.strftime("%d/%m/%Y"),
                    clase="4",
                    tipo=tipo_doc,
                    numero_doc_del=codigo_generacion,
                    numero_doc_al=codigo_generacion,
                    ventas_exentas=_format_decimal(componentes[0]),
                    internas_exentas_ns=_format_decimal(componentes[1]),
                    ventas_no_sujetas=_format_decimal(componentes[2]),
                    ventas_gravadas_locales=_format_decimal(componentes[3]),
                    exp_ca=_format_decimal(componentes[4]),
                    exp_fuera_ca=_format_decimal(componentes[5]),
                    exp_servicios=_format_decimal(componentes[6]),
                    zonas_francas_dpa=_format_decimal(componentes[7]),
                    terceros_no_domic=_format_decimal(componentes[8]),
                    total_ventas=_format_decimal(total_componentes),
                    tipo_operacion=_normalize_tipo(ident_raw.get("tipoOperacion")),
                    tipo_ingreso=_normalize_tipo(resumen.get("tipoIngreso")),
                )

                hora_text = str(
                    ident_raw.get("horEmi")
                    or ident_raw.get("horaEmision")
                    or ident_raw.get("horEmision")
                    or ""
                ).strip()
                orden_dt = datetime.combine(fecha_only, dt_time.min)
                if hora_text:
                    for fmt in ("%H:%M:%S", "%H:%M"):
                        try:
                            hora_obj = datetime.strptime(hora_text, fmt).time()
                        except ValueError:
                            continue
                        orden_dt = datetime.combine(fecha_only, hora_obj)
                        break

                registro.numero_control = numero_control
                registro.codigo_generacion = codigo_generacion
                registro.json_path = str(json_path)

                seen_codigos.add(codigo_generacion)
                registros.append((orden_dt, numero_control, registro))

        registros.sort(key=lambda item: (item[0], item[1]))
        return [item[2] for item in registros]

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

    def delete_compra(self, compra_id: int) -> None:
        """Elimina una compra y actualiza las vistas relacionadas."""

        self.db.delete_compra(compra_id)
        self.refresh_data()

    def delete_detalle_compra(self, detalle_id: int) -> None:
        """Elimina un lote específico y sincroniza el inventario."""

        self.db.delete_detalle_compra(detalle_id)
        self.refresh_data()

    def update_detalle_compra_cantidad(self, detalle_id: int, nueva_cantidad: int) -> None:
        """Actualiza la cantidad de un lote específico y refresca los datos."""

        self.db.update_detalle_compra_cantidad(detalle_id, nueva_cantidad)
        self.refresh_data()

    def exportar_inventario_json(self, filename, tab_order=None):
        datos_negocio = {}
        if os.path.exists(DATOS_NEGOCIO_PATH):
            try:
                with open(DATOS_NEGOCIO_PATH, "r", encoding="utf-8") as f:
                    datos_negocio = json.load(f)
                    if not isinstance(datos_negocio, dict):
                        datos_negocio = {}
            except Exception:
                logger.exception("Failed to parse %s", DATOS_NEGOCIO_PATH)
                datos_negocio = {}

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
                write_array("distribuidores", (dict(v) for v in self._Distribuidores))
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
                sanitized_negocio = _sanitize_datos_negocio(datos_negocio)
                if sanitized_negocio:
                    f.write(",\n\"datos_negocio\":")
                    try:
                        json.dump(sanitized_negocio, f, ensure_ascii=False)
                    except TypeError:
                        f.write(
                            json.dumps(
                                sanitized_negocio,
                                ensure_ascii=False,
                                cls=DecimalEncoder,
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

        log_path = user_logs_path(
            f"import_inventory_{datetime.now():%Y%m%d_%H%M%S}.log"
        )
        handler = logging.FileHandler(str(log_path), encoding="utf-8")
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
        productos_por_id = {
            p.get("id"): p for p in data.get("productos", []) if isinstance(p, dict)
        }
        compras_por_id = {
            c.get("id"): c for c in data.get("compras", []) if isinstance(c, dict)
        }
        cliente_id_map = {}
        venta_id_map = {}
        compra_id_map: dict[object, int] = {}
        trabajador_id_map = {}
        detalle_compra_id_map: dict[object, int] = {}

        def _coerce_int(value):
            if value in (None, ""):
                return None
            if isinstance(value, int):
                return value
            try:
                return int(str(value))
            except (TypeError, ValueError):
                return None

        self.db.ensure_column("ventas", "sincronizada", "INTEGER DEFAULT 1")
        # Asegura que las columnas de ``dte_envios`` necesarias para los estados
        # manuales existan antes de intentar restaurar los datos exportados.
        self.db.ensure_column("dte_envios", "codigo_lote", "TEXT")
        self.db.ensure_column("dte_envios", "codigo_generacion", "TEXT")
        self.db.ensure_column("dte_envios", "numero_control", "TEXT")
        self.db.ensure_column("dte_envios", "ambiente", "TEXT")
        self.db.ensure_column("dte_envios", "estado_ui", "TEXT")
        self.db.ensure_column("dte_envios", "estado_ui_tag", "TEXT")
        self.db.ensure_column("dte_envios", "estado_ui_manual", "INTEGER DEFAULT 0")

        self.db.conn.execute("BEGIN")
        try:
            raw_vendedores = data.get("vendedores", [])
            employee_vendor_data = {}
            supplier_vendors = []
            for vend in raw_vendedores:
                if vend.get("Distribuidor_id") is None:
                    employee_vendor_data[vend.get("id")] = vend
                else:
                    supplier_vendors.append(vend)

            # --- Distribuidores primero ---
            for v in data.get("distribuidores", []):
                self.db.add_Distribuidor_detallado(v, commit=False)
                self.db.cursor.execute(
                    "SELECT id FROM Distribuidores WHERE nombre=? ORDER BY id DESC LIMIT 1",
                    (v["nombre"],),
                )
                new_id = self.db.cursor.fetchone()["id"]
                Distribuidor_id_map[v["id"]] = new_id

            for t in data.get("trabajadores", []):
                empleado_vendor = employee_vendor_data.get(t.get("id"), {})
                codigo = t.get("codigo") or empleado_vendor.get("codigo")
                existing = None
                if codigo:
                    self.db.cursor.execute(
                        "SELECT id FROM trabajadores WHERE codigo=?",
                        (codigo,),
                    )
                    existing = self.db.cursor.fetchone()
                if existing:
                    tid = existing["id"]
                    if not codigo:
                        codigo = existing["codigo"]
                    self.db.cursor.execute(
                        """
                        UPDATE trabajadores SET
                            codigo=?, nombre=?, dui=?, nit=?, fecha_nacimiento=?, cargo=?, area=?, fecha_contratacion=?,
                            telefono=?, email=?, direccion=?, salario_base=?, comentarios=?, es_vendedor=?
                        WHERE id=?
                        """,
                        (
                            codigo or "",
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
                    trabajador_data = dict(t)
                    if codigo:
                        trabajador_data["codigo"] = codigo
                    self.db.add_trabajador(trabajador_data, commit=False)
                    tid = self.db.cursor.lastrowid
                    if not codigo:
                        self.db.cursor.execute(
                            "SELECT codigo FROM trabajadores WHERE id=?",
                            (tid,),
                        )
                        row = self.db.cursor.fetchone()
                        codigo = row["codigo"] if row else codigo
                trabajador_id_map[t.get("id")] = tid
                if t.get("es_vendedor"):
                    dist_id = t.get("Distribuidor_id")
                    new_dist_id = (
                        Distribuidor_id_map.get(dist_id)
                        if dist_id is not None
                        else None
                    )
                    vendedor_codigo = codigo or empleado_vendor.get("codigo")
                    descripcion = empleado_vendor.get(
                        "descripcion", t.get("descripcion", "")
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
                                vendedor_codigo,
                                t.get("nombre"),
                                t.get("dui"),
                                descripcion,
                                new_dist_id,
                            ),
                        )
                    else:
                        self.db.cursor.execute(
                            "UPDATE vendedores SET codigo=?, nombre=?, dui=?, descripcion=?, Distribuidor_id=? WHERE id=?",
                            (
                                vendedor_codigo,
                                t.get("nombre"),
                                t.get("dui"),
                                descripcion,
                                new_dist_id,
                                tid,
                            ),
                        )
                    vendedor_id_map[t.get("id")] = tid

            # --- Vendedores distribuidores, usando el mapeo correcto ---
            for vend in supplier_vendors:
                dist_id = vend.get("Distribuidor_id")
                new_dist_id = (
                    Distribuidor_id_map.get(dist_id) if dist_id is not None else None
                )
                existing_id = None
                codigo = vend.get("codigo")
                if codigo:
                    self.db.cursor.execute(
                        "SELECT id FROM vendedores WHERE codigo=?",
                        (codigo,),
                    )
                    row = self.db.cursor.fetchone()
                    if row:
                        existing_id = row["id"]

                if existing_id is not None:
                    self.db.cursor.execute(
                        """
                        UPDATE vendedores
                        SET nombre=?, descripcion=?, Distribuidor_id=?, codigo=?, dui=?
                        WHERE id=?
                        """,
                        (
                            vend["nombre"],
                            vend.get("descripcion", ""),
                            new_dist_id,
                            codigo,
                            vend.get("dui"),
                            existing_id,
                        ),
                    )
                    new_id = existing_id
                else:
                    self.db.add_vendedor(
                        vend["nombre"],
                        vend.get("descripcion", ""),
                        new_dist_id,
                        codigo,
                        vend.get("dui"),
                        commit=False,
                    )
                    self.db.cursor.execute(
                        "SELECT id FROM vendedores WHERE nombre=? ORDER BY id DESC LIMIT 1",
                        (vend["nombre"],),
                    )
                    new_id = self.db.cursor.fetchone()["id"]

                vendedor_id_map[vend["id"]] = new_id

            # Productos
            for p in data.get("productos", []):
                old_vend_id = p.get("vendedor_id")
                vend = vendedor_id_map.get(old_vend_id)
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
                vendedor_id = trabajador_id_map.get(old_vend_id)
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
                old_id_raw = c.get("id")
                specified_id = _coerce_int(old_id_raw)
                columns = [
                    "fecha",
                    "producto_id",
                    "cantidad",
                    "precio_unitario",
                    "total",
                    "Distribuidor_id",
                    "comision_pct",
                    "comision_monto",
                    "vendedor_id",
                ]
                values = [
                    c.get("fecha", ""),
                    None,
                    0,
                    0,
                    c.get("total", 0),
                    Distribuidor_id,
                    comision_pct,
                    comision_monto,
                    vendedor_id,
                ]
                if specified_id is not None:
                    columns.insert(0, "id")
                    values.insert(0, specified_id)
                placeholders = ", ".join(["?"] * len(values))
                self.db.cursor.execute(
                    f"INSERT INTO compras ({', '.join(columns)}) VALUES ({placeholders})",
                    tuple(values),
                )
                new_id = specified_id if specified_id is not None else self.db.cursor.lastrowid
                if old_id_raw is not None:
                    compra_id_map[old_id_raw] = new_id
                    compra_id_map[str(old_id_raw)] = new_id
                if specified_id is not None:
                    compra_id_map[specified_id] = new_id

            detalles_por_compra: dict[object, list[dict]] = {}
            for detalle in data.get("detalles_compra", []):
                if not isinstance(detalle, dict):
                    continue
                compra_key = detalle.get("compra_id")
                if compra_key is None:
                    continue
                detalles_por_compra.setdefault(compra_key, []).append(detalle)

            def _to_decimal(value) -> D:
                try:
                    if value is None or value == "":
                        return D("0")
                    return D(str(value))
                except (ArithmeticError, ValueError, TypeError):
                    return D("0")

            def _maybe_create_missing_purchase(compra_key, detalles_list):
                if compra_key in compra_id_map:
                    return

                compra_info = compras_por_id.get(compra_key, {}) if compras_por_id else {}
                base_total = D("0")
                total_comision = D("0")
                for det in detalles_list:
                    cantidad = _to_decimal(det.get("cantidad"))
                    precio = _to_decimal(det.get("precio_unitario"))
                    subtotal = cantidad * precio
                    descuento = _to_decimal(det.get("descuento"))
                    subtotal_con_descuento = subtotal - descuento
                    if subtotal_con_descuento < 0:
                        subtotal_con_descuento = D("0")
                    iva = _to_decimal(det.get("iva"))
                    iva_tipo = str(det.get("iva_tipo") or "").strip().lower()
                    comision_monto = _to_decimal(det.get("comision_monto"))
                    comision_tipo = str(det.get("comision_tipo") or "").strip().lower()
                    total_linea = subtotal_con_descuento
                    if iva_tipo == "añadido" or iva_tipo == "anadido":
                        total_linea += iva
                    if comision_tipo in {"añadida al total", "anadida al total"}:
                        total_linea += comision_monto
                    base_total += total_linea
                    total_comision += comision_monto

                if base_total == 0 and not compra_info:
                    # Nothing meaningful to persist
                    return

                mapped_dist = None
                mapped_vendor = None
                if compra_info:
                    dist_id = compra_info.get("Distribuidor_id")
                    if dist_id is not None:
                        mapped_dist = Distribuidor_id_map.get(dist_id)
                    vend_id = compra_info.get("vendedor_id")
                    if vend_id is not None:
                        mapped_vendor = vendedor_id_map.get(vend_id)

                comision_pct = compra_info.get("comision_pct", 0) if compra_info else 0
                comision_monto = compra_info.get("comision_monto")
                if comision_monto is None:
                    comision_monto = float(total_comision)

                old_id = _coerce_int(compra_key)
                columns = [
                    "fecha",
                    "producto_id",
                    "cantidad",
                    "precio_unitario",
                    "total",
                    "Distribuidor_id",
                    "comision_pct",
                    "comision_monto",
                    "vendedor_id",
                ]
                values = [
                    (compra_info.get("fecha") if compra_info else "") or "",
                    None,
                    0,
                    0,
                    float(base_total) if base_total else compra_info.get("total", 0),
                    mapped_dist,
                    comision_pct,
                    comision_monto,
                    mapped_vendor,
                ]
                if old_id is not None:
                    columns.insert(0, "id")
                    values.insert(0, old_id)
                placeholders = ", ".join(["?"] * len(values))
                self.db.cursor.execute(
                    f"INSERT INTO compras ({', '.join(columns)}) VALUES ({placeholders})",
                    tuple(values),
                )
                new_id = old_id if old_id is not None else self.db.cursor.lastrowid
                compra_id_map[compra_key] = new_id
                compra_id_map[str(compra_key)] = new_id
                if old_id is not None:
                    compra_id_map[old_id] = new_id

            for compra_key, detalles_list in detalles_por_compra.items():
                _maybe_create_missing_purchase(compra_key, detalles_list)

            # Detalles de compra
            for d in data.get("detalles_compra", []):
                compra_id = compra_id_map.get(d.get("compra_id"))
                if not compra_id:
                    continue
                old_producto_id = d.get("producto_id")
                producto_id = producto_id_map.get(old_producto_id)
                if producto_id is None and old_producto_id is not None:
                    producto_info = productos_por_id.get(old_producto_id)
                    if producto_info:
                        vend = vendedor_id_map.get(producto_info.get("vendedor_id"))
                        dist = Distribuidor_id_map.get(producto_info.get("Distribuidor_id"))
                        stock = producto_info.get("stock", 0)
                        try:
                            stock = float(stock) if stock is not None else 0
                        except (TypeError, ValueError):
                            stock = 0
                        self.db.add_producto(
                            producto_info.get("nombre", f"Producto {old_producto_id}"),
                            producto_info.get("codigo", ""),
                            producto_info.get("sku"),
                            vend,
                            dist,
                            producto_info.get("precio_compra", 0),
                            producto_info.get("precio_venta_minorista", 0),
                            producto_info.get("precio_venta_mayorista", 0),
                            stock,
                            commit=False,
                        )
                        producto_id = self.db.cursor.lastrowid
                        producto_id_map[old_producto_id] = producto_id
                    else:
                        try:
                            self.db.add_producto(
                                f"Producto {old_producto_id}",
                                "",
                                None,
                                None,
                                None,
                                d.get("precio_unitario", 0),
                                d.get("precio_unitario", 0),
                                d.get("precio_unitario", 0),
                                d.get("cantidad", 0),
                                commit=False,
                            )
                            producto_id = self.db.cursor.lastrowid
                            producto_id_map[old_producto_id] = producto_id
                        except Exception:
                            logger.exception(
                                "No fue posible recrear el producto %s para el detalle de compra",
                                old_producto_id,
                            )
                            producto_id = None
                if compra_id and producto_id:
                    old_detalle_id = d.get("id")
                    specified_detalle_id = _coerce_int(old_detalle_id)
                    columns = [
                        "compra_id",
                        "producto_id",
                        "cantidad",
                        "precio_unitario",
                        "fecha_vencimiento",
                        "descuento",
                        "descuento_tipo",
                        "iva",
                        "iva_tipo",
                        "comision_pct",
                        "comision_monto",
                        "comision_tipo",
                    ]
                    values = [
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
                    ]
                    if specified_detalle_id is not None:
                        columns.insert(0, "id")
                        values.insert(0, specified_detalle_id)
                    placeholders = ", ".join(["?"] * len(values))
                    self.db.cursor.execute(
                        f"INSERT INTO detalles_compra ({', '.join(columns)}) VALUES ({placeholders})",
                        tuple(values),
                    )
                    new_detalle_id = (
                        specified_detalle_id
                        if specified_detalle_id is not None
                        else self.db.cursor.lastrowid
                    )
                    if old_detalle_id is not None:
                        detalle_compra_id_map[old_detalle_id] = new_detalle_id
                        detalle_compra_id_map[str(old_detalle_id)] = new_detalle_id
                    if specified_detalle_id is not None:
                        detalle_compra_id_map[specified_detalle_id] = new_detalle_id

            # Ajustar secuencias de AUTOINCREMENT para compras y detalles de compra
            max_compra_id = (
                self.db.cursor.execute("SELECT MAX(id) FROM compras").fetchone()[0] or 0
            )
            self.db.cursor.execute(
                "UPDATE sqlite_sequence SET seq=? WHERE name='compras'",
                (max_compra_id,),
            )
            max_detalle_compra_id = (
                self.db.cursor.execute("SELECT MAX(id) FROM detalles_compra").fetchone()[0]
                or 0
            )
            self.db.cursor.execute(
                "UPDATE sqlite_sequence SET seq=? WHERE name='detalles_compra'",
                (max_detalle_compra_id,),
            )

            def _remap_lote_references(value):
                if isinstance(value, dict):
                    updated = {}
                    for key, item in value.items():
                        if key in {"lote_id", "loteId", "lote"}:
                            replacement = detalle_compra_id_map.get(item, item)
                            if replacement is item:
                                replacement = detalle_compra_id_map.get(str(item), item)
                            updated[key] = replacement
                        else:
                            updated[key] = _remap_lote_references(item)
                    return updated
                if isinstance(value, list):
                    return [_remap_lote_references(item) for item in value]
                return detalle_compra_id_map.get(value, value)

            # Detalles de venta
            for d in data.get("detalles_venta", []):
                venta_id = venta_id_map.get(d.get("venta_id"))
                producto_id = producto_id_map.get(d.get("producto_id"))
                vendedor_id = None
                old_vend_id = d.get("vendedor_id")
                if old_vend_id is not None:
                    vendedor_id = trabajador_id_map.get(old_vend_id)
                    if vendedor_id is None:
                        logger.warning(
                            "detalle_venta vendedor_id %s not found in mapping, defaulting to None",
                            old_vend_id,
                        )
                if venta_id and producto_id:
                    extra = d.get("extra", None)
                    extra_was_string = isinstance(extra, str)
                    if extra_was_string:
                        text = extra.strip()
                        if text:
                            try:
                                extra = json.loads(text)
                            except Exception:
                                extra = text
                    remapped_extra = _remap_lote_references(extra)
                    if remapped_extra is None:
                        extra_value = None
                    elif isinstance(remapped_extra, (dict, list)):
                        try:
                            extra_value = json.dumps(remapped_extra)
                        except Exception:
                            extra_value = json.dumps(remapped_extra, default=str)
                    elif isinstance(remapped_extra, str):
                        extra_value = remapped_extra
                    else:
                        if extra_was_string:
                            extra_value = json.dumps(remapped_extra)
                        else:
                            extra_value = remapped_extra

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
                            extra_value,
                            d.get("precio_con_iva", 0),
                            vendedor_id,
                        ),
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

            def _normalize_text(value):
                if isinstance(value, str):
                    text = value.strip()
                    return text or None
                return value

            def _normalize_tag(value):
                if isinstance(value, str):
                    text = value.strip().lower()
                    return text or None
                return None if value in ("", None) else value

            def _normalize_manual(value):
                if value is None:
                    return None
                if isinstance(value, bool):
                    return 1 if value else 0
                try:
                    intval = int(value)
                except (TypeError, ValueError):
                    if isinstance(value, str):
                        lowered = value.strip().lower()
                        if not lowered:
                            return None
                        if lowered in {"true", "sí", "si", "yes"}:
                            return 1
                        if lowered in {"false", "no"}:
                            return 0
                    return None
                return 1 if intval else 0

            for de in data.get("dte_envios", []):
                codigo_lote = _normalize_text(de.get("codigo_lote") or de.get("codigoLote"))
                codigo_generacion = _normalize_text(
                    de.get("codigo_generacion")
                    or de.get("codigoGeneracion")
                )
                numero_control = _normalize_text(
                    de.get("numero_control") or de.get("numeroControl")
                )
                ambiente = _normalize_text(de.get("ambiente"))
                estado_ui = _normalize_text(de.get("estado_ui"))
                estado_ui_tag = _normalize_tag(de.get("estado_ui_tag"))
                estado_ui_manual = _normalize_manual(de.get("estado_ui_manual"))

                self.db.cursor.execute(
                    """
                    INSERT INTO dte_envios (
                        venta_id, modo, estado, sello, fecha_hora, respuesta,
                        codigo_lote, codigo_generacion, numero_control, ambiente,
                        estado_ui, estado_ui_tag, estado_ui_manual
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        venta_id_map.get(de.get("venta_id")),
                        de.get("modo"),
                        de.get("estado"),
                        de.get("sello"),
                        de.get("fecha_hora"),
                        de.get("respuesta"),
                        codigo_lote,
                        codigo_generacion,
                        numero_control,
                        ambiente,
                        estado_ui,
                        estado_ui_tag,
                        estado_ui_manual,
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
                if extra is None:
                    extra_json = None
                elif isinstance(extra, str):
                    extra_json = extra
                elif isinstance(extra, (dict, list)):
                    extra_json = json.dumps(extra)
                else:
                    extra_json = json.dumps(extra)
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
        existing_tokens = {}
        if os.path.exists(datos_path):
            try:
                with open(datos_path, "r", encoding="utf-8") as f:
                    existing_tokens = _extract_manual_tokens(json.load(f))
            except Exception:
                logger.exception("Failed to parse %s", datos_path)
                existing_tokens = {}

        if "datos_negocio" in data:
            datos_negocio = data.get("datos_negocio")
            if datos_negocio is not None:
                sanitized = _sanitize_datos_negocio(datos_negocio)
                if existing_tokens:
                    dte_api = sanitized.setdefault("dte_api", {})
                    dte_api.update(existing_tokens)
                with open(datos_path, "w", encoding="utf-8") as f:
                    json.dump(sanitized, f, ensure_ascii=False, indent=2)
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
            tipo_fiscal_raw = item.get("tipo_fiscal", "gravada")
            tipo_fiscal_norm = normalize_tipo_fiscal(tipo_fiscal_raw)
            iva_rate = D("0.13") if tipo_fiscal_norm == "gravada" else D("0")
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
                "tipo_fiscal": tipo_fiscal_norm,
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