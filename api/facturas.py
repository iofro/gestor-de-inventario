from fastapi import Depends, FastAPI, HTTPException, Request
from facturas_db.facturas_repo import FacturasRepo
from pydantic import BaseModel, Field, root_validator, validator
import logging

logger = logging.getLogger(__name__)

app = FastAPI()


def get_repo(request: Request) -> FacturasRepo:
    repo = getattr(request.app.state, "facturas_repo", None)
    if repo is None:
        repo = FacturasRepo()
        request.app.state.facturas_repo = repo
    return repo


class ContingenciaIn(BaseModel):
    modeloFacturacion: int = Field(2, description="Modelo de facturación para contingencia")
    tipoTransmision: int = Field(2, description="Tipo de transmisión para contingencia")
    tipoContingencia: int
    motivoContingencia: str | None = None

    @root_validator(pre=True)
    def _compat_motivo(cls, values: dict) -> dict:
        legacy = values.get("motivoContin")
        if values.get("motivoContingencia") is None and legacy is not None:
            values["motivoContingencia"] = legacy
        return values

    @validator("modeloFacturacion")
    def _modelo_valido(cls, value: int) -> int:
        if value != 2:
            raise ValueError("modeloFacturacion debe ser 2 en modo contingencia")
        return value

    @validator("tipoTransmision")
    def _transmision_valida(cls, value: int) -> int:
        if value != 2:
            raise ValueError("tipoTransmision debe ser 2 en modo contingencia")
        return value

    @validator("tipoContingencia")
    def _tipo_valido(cls, value: int) -> int:
        if value not in {1, 2, 3, 4, 5}:
            raise ValueError("Tipo de contingencia inválido")
        return value

    @validator("motivoContingencia", always=True)
    def _motivo_validado(cls, value: str | None, values: dict) -> str | None:
        tipo = values.get("tipoContingencia")
        if tipo == 5:
            if not value or not value.strip():
                raise ValueError(
                    "Motivo es obligatorio cuando el tipo es 'Otro' (máx. 500)."
                )
            trimmed = value.strip()
            if len(trimmed) > 500:
                trimmed = trimmed[:500]
            return trimmed
        return None


@app.post("/api/facturas/{factura_id}/contingencia")
def guardar_en_contingencia(
    factura_id: int,
    data: ContingenciaIn,
    repo: FacturasRepo = Depends(get_repo),
):
    factura = repo.get(factura_id)
    if not factura:
        raise HTTPException(status_code=404, detail="Factura no encontrada")
    if factura.estado_envio == "Enviado":
        raise HTTPException(status_code=400, detail="Factura ya enviada")
    repo.guardar_en_contingencia(
        factura_id, data.tipoContingencia, data.motivoContingencia
    )
    logger.info("accion=forzar_contingencia_por_usuario factura_id=%s", factura_id)
    return {"ok": True, "factura": factura.to_dict()}
