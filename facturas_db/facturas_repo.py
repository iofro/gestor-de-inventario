from __future__ import annotations
from typing import Dict, Optional
from models.factura import Factura

class FacturasRepo:
    """Repositorio simple en memoria para facturas."""

    def __init__(self) -> None:
        self._data: Dict[int, Factura] = {}

    def add(self, factura: Factura) -> None:
        self._data[factura.id] = factura

    def get(self, factura_id: int) -> Optional[Factura]:
        return self._data.get(factura_id)

    def guardar_en_contingencia(self, factura_id: int) -> Optional[Factura]:
        factura = self.get(factura_id)
        if not factura:
            return None
        factura.modo_transmision = "contingencia"
        factura.estado_envio = "Pendiente"
        return factura
