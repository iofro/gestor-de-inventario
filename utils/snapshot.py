"""Helpers for working with persisted DTE snapshots."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping

__all__ = ["Snapshot", "SnapshotNotFoundError", "normalize_snapshot"]


@dataclass(frozen=True)
class Snapshot:
    """Metadata for a stored DTE snapshot."""

    uuid: str
    path: str
    tipo_documento: str | None
    fecha_emision: str | None
    payload: dict[str, Any]


class SnapshotNotFoundError(RuntimeError):
    """Raised when the expected snapshot is not available."""

    def __init__(self, venta_id: int, nota_id: int | None = None):
        message = f"No se encontró snapshot para venta {venta_id}"
        if nota_id is not None:
            message += f" (nota {nota_id})"
        super().__init__(message)
        self.venta_id = venta_id
        self.nota_id = nota_id


_TRANSIENT_ROOT_KEYS = {
    "acuse",
    "acuseRecibo",
    "acuseRecepcion",
    "acuseRecepcionMH",
    "acuseMH",
    "acuseDte",
    "firma",
    "firmaElectronica",
    "firmaDigital",
    "sello",
    "selloRecepcion",
    "selloRecibido",
    "selloMH",
    "estado",
    "estadoDte",
    "estadoTransmision",
    "estadoEnvio",
    "respuesta",
    "respuestaMH",
}


def _clean_identificacion(data: Mapping[str, Any]) -> dict[str, Any]:
    ident = dict(data)
    tipo = ident.get("tipoDte")
    if isinstance(tipo, int):
        ident["tipoDte"] = f"{tipo:02d}"
    elif isinstance(tipo, str):
        stripped = tipo.strip()
        if stripped.isdigit() and len(stripped) <= 2:
            ident["tipoDte"] = f"{int(stripped):02d}"
        elif stripped:
            ident["tipoDte"] = stripped
    codigo = ident.get("codigoGeneracion")
    if isinstance(codigo, str):
        ident["codigoGeneracion"] = codigo.strip().upper()
    fecha = ident.get("fechaEmision")
    if fecha and not ident.get("fecEmi"):
        ident["fecEmi"] = fecha
    if ident.get("fechaEmision") in {None, ""}:
        ident.pop("fechaEmision", None)
    return ident


def normalize_snapshot(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return a sanitised copy of ``payload`` suitable for reuse."""

    if not isinstance(payload, Mapping):
        raise TypeError("snapshot payload debe ser un mapeo")
    data = deepcopy(payload)
    for key in _TRANSIENT_ROOT_KEYS:
        data.pop(key, None)
    ident = data.get("identificacion")
    if isinstance(ident, Mapping):
        data["identificacion"] = _clean_identificacion(ident)
    return data
