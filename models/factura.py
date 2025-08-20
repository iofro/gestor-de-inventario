from dataclasses import dataclass

@dataclass
class Factura:
    id: int
    modo_transmision: str = "normal"
    estado_envio: str = "Pendiente"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "modo_transmision": self.modo_transmision,
            "estado_envio": self.estado_envio,
        }
