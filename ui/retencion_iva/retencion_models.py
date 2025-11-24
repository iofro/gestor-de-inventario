"""Modelos ligeros (solo UI) para Comprobante de Retención."""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class CRDetalle:
    tipoDte: str
    tipoDoc: str
    numDocumento: Optional[str] = None
    codGeneracion: Optional[str] = None
    fechaEmision: str = ""
    montoSujetoGrav: float = 0.0
    codigoRetencionMH: str = "22"
    ivaRetenido: float = 0.0
    descripcion: str = ""


@dataclass
class CRResumen:
    totalSujetoRetencion: float = 0.0
    totalIVAretenido: float = 0.0
    totalIVAretenidoLetras: str = ""


@dataclass
class CRDraft:
    detalles: List[CRDetalle] = field(default_factory=list)
    resumen: CRResumen = field(default_factory=CRResumen)
    meta: dict = field(default_factory=dict)  # emisor/receptor/identificación (solo UI)

