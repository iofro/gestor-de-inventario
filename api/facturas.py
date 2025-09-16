from fastapi import Depends, FastAPI, HTTPException, Request
from facturas_db.facturas_repo import FacturasRepo
from pydantic import BaseModel
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
    tipoContingencia: int
    motivoContin: str | None = None


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
        factura_id, data.tipoContingencia, data.motivoContin
    )
    logger.info("accion=forzar_contingencia_por_usuario factura_id=%s", factura_id)
    return {"ok": True, "factura": factura.to_dict()}
