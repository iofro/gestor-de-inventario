from fastapi import FastAPI, HTTPException
from facturas_db.facturas_repo import FacturasRepo
from models.factura import Factura
import logging

logger = logging.getLogger(__name__)

app = FastAPI()
repo = FacturasRepo()

@app.post("/api/facturas/{factura_id}/contingencia")
def guardar_en_contingencia(factura_id: int):
    factura = repo.get(factura_id)
    if not factura:
        raise HTTPException(status_code=404, detail="Factura no encontrada")
    if factura.estado_envio == "Enviado":
        raise HTTPException(status_code=400, detail="Factura ya enviada")
    repo.guardar_en_contingencia(factura_id)
    logger.info("accion=forzar_contingencia_por_usuario factura_id=%s", factura_id)
    return {"ok": True, "factura": factura.to_dict()}
