from dataclasses import dataclass

@dataclass
class Factura:
    id: int
    modo_transmision: str = "normal"
    estado_envio: str = "Pendiente"
    tipo_contingencia: int | None = None
    motivo_contin: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "modo_transmision": self.modo_transmision,
            "estado_envio": self.estado_envio,
            "tipo_contingencia": self.tipo_contingencia,
            "motivo_contin": self.motivo_contin,
        }
