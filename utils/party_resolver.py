"""Utilities to resolve vendor and distributor names consistently."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any, Mapping, MutableMapping, Sequence, TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing helpers only
    from db import DB


logger = logging.getLogger(__name__)


@dataclass
class Catalogs:
    """Container that groups vendor, distributor and product catalogs."""

    vendors: MutableMapping[int, Mapping[str, Any]]
    distributors: MutableMapping[int, Mapping[str, Any]]
    products: MutableMapping[int, Mapping[str, Any]]
    db: "DB | None" = None


_VENDOR_ID_KEYS: tuple[str, ...] = (
    "vendedor_id",
    "vendor_id",
    "seller_id",
    "id_vendedor",
    "vendorId",
    "vendedorId",
    "Proveedor_id",
    "proveedor_id",
)
_VENDOR_NAME_KEYS: tuple[str, ...] = (
    "vendedor_nombre",
    "vendor_name",
    "vendedor",
    "vendor",
    "seller",
    "seller_name",
    "proveedor",
    "proveedor_nombre",
    "ProveedorNombre",
)
_DISTRIBUTOR_ID_KEYS: tuple[str, ...] = (
    "Distribuidor_id",
    "distribuidor_id",
    "distributor_id",
    "DistribuidorId",
    "DistributorID",
)
_DISTRIBUTOR_NAME_KEYS: tuple[str, ...] = (
    "Distribuidor_nombre",
    "distribuidor_nombre",
    "DistribuidorNombre",
    "distributor_name",
    "distribuidor",
    "distributor",
)


def normalize_identifier(value: Any) -> int | None:
    """Return a normalized identifier or ``None`` when not applicable."""

    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value.is_integer():
            return int(value)
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return int(text)
        except ValueError:
            try:
                float_value = float(text)
            except ValueError:
                return None
            if float_value.is_integer():
                return int(float_value)
            return None
    return None


def _get_first(mapping: Mapping[str, Any], keys: Sequence[str]) -> Any:
    for key in keys:
        if key in mapping and mapping[key] not in (None, ""):
            return mapping[key]
    return None


def _coerce_text(value: Any) -> str | None:
    if isinstance(value, str):
        text = value.strip()
        if text:
            if text.isdigit():
                return None
            return text
    return None


def _extract_name(source: Mapping[str, Any], keys: Sequence[str]) -> str | None:
    raw = _get_first(source, keys)
    if raw is None:
        return None
    if isinstance(raw, str):
        text = raw.strip()
        if text:
            if text.isdigit():
                return None
            return text
    return None


def _extract_identifier(source: Mapping[str, Any], keys: Sequence[str]) -> int | None:
    for key in keys:
        if key not in source:
            continue
        normalized = normalize_identifier(source[key])
        if normalized is not None:
            return normalized
    return None


def _query_name(db: "DB | None", table: str, record_id: int) -> str | None:
    if db is None:
        return None
    try:
        db.cursor.execute(f"SELECT nombre FROM {table} WHERE id=?", (record_id,))
        row = db.cursor.fetchone()
    except Exception:  # pragma: no cover - defensive logging
        logger.exception("No fue posible obtener el nombre de %s con id %s", table, record_id)
        return None
    if not row:
        return None
    if isinstance(row, tuple):
        value = row[0]
    else:
        try:
            value = row["nombre"]
        except Exception:  # pragma: no cover - sqlite row variants
            getter = getattr(row, "get", None)
            value = getter("nombre") if callable(getter) else None
    if isinstance(value, str):
        return value.strip() or None
    return None


def resolve_party_names(purchase: Mapping[str, Any], catalogs: Catalogs | None) -> tuple[str, str]:
    """Resolve vendor and distributor names for *purchase*.

    The resolution strategy prioritises the purchase payload, then shared
    catalogs and finally database lookups if catalogues are incomplete.
    """

    if not isinstance(purchase, Mapping):
        purchase = dict(purchase)  # type: ignore[arg-type]

    if catalogs is None:
        catalogs = Catalogs(vendors={}, distributors={}, products={})

    vendor_name = _extract_name(purchase, _VENDOR_NAME_KEYS)
    distributor_name = _extract_name(purchase, _DISTRIBUTOR_NAME_KEYS)
    vendor_id = _extract_identifier(purchase, _VENDOR_ID_KEYS)
    distributor_id = _extract_identifier(purchase, _DISTRIBUTOR_ID_KEYS)

    vendor_entry = catalogs.vendors.get(vendor_id) if vendor_id is not None else None
    if vendor_entry and vendor_name is None:
        vendor_name = _extract_name(vendor_entry, _VENDOR_NAME_KEYS) or _coerce_text(vendor_entry.get("nombre"))

    if distributor_id is None and vendor_entry is not None:
        distributor_id = _extract_identifier(vendor_entry, _DISTRIBUTOR_ID_KEYS)

    if distributor_name is None and distributor_id is not None:
        distributor_entry = catalogs.distributors.get(distributor_id)
        if distributor_entry:
            distributor_name = (
                _extract_name(distributor_entry, _DISTRIBUTOR_NAME_KEYS)
                or _coerce_text(distributor_entry.get("nombre"))
            )

    if vendor_name is None and vendor_id is not None:
        vendor_name = _query_name(catalogs.db, "vendedores", vendor_id)
        if vendor_name:
            catalogs.vendors.setdefault(vendor_id, {"id": vendor_id, "nombre": vendor_name})

    if distributor_name is None and distributor_id is not None:
        distributor_name = _query_name(catalogs.db, "Distribuidores", distributor_id)
        if distributor_name:
            catalogs.distributors.setdefault(
                distributor_id,
                {"id": distributor_id, "nombre": distributor_name},
            )

    if vendor_name is None:
        if vendor_id is None:
            logger.info("Compra %s no tiene vendedor asociado", purchase.get("id"))
        else:
            logger.info(
                "No se encontró nombre del vendedor %s en catálogos ni base de datos",
                vendor_id,
            )

    if distributor_name is None:
        if distributor_id is None:
            logger.info("Compra %s no especifica distribuidor", purchase.get("id"))
        else:
            logger.info(
                "No se encontró nombre del distribuidor %s en catálogos ni base de datos",
                distributor_id,
            )

    return vendor_name or "Desconocido", distributor_name or "Desconocido"

