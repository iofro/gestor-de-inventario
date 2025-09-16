from __future__ import annotations

from fastapi import FastAPI, HTTPException
from db import DB
from dte import enviar_nota_credito, enviar_nota_debito
from facturas_db.facturas_repo import FacturasRepo
from models.factura import Factura  # noqa: F401 - reexport for tests

app = FastAPI()
db = DB(":memory:")
repo = FacturasRepo(db)


@app.get("/api/facturas/{factura_id}")
def obtener_factura(factura_id: int):
    factura = repo.get(factura_id)
    if not factura:
        raise HTTPException(status_code=404, detail="Factura no encontrada")
    return {"factura": factura.to_dict()}


@app.post("/api/notas")
def crear_y_transmitir_nota(payload: dict):
    tipo = payload.get("tipo")
    venta_id = payload.get("venta_id")
    fecha = payload.get("fecha")
    monto = payload.get("monto", 0)
    motivo = payload.get("motivo")
    detalles = payload.get("detalles")
    try:
        nota_id = db.agregar_nota(tipo, venta_id, fecha, monto, motivo, detalles)
    except ValueError as exc:  # pragma: no cover - fastapi handles
        raise HTTPException(status_code=400, detail=str(exc))

    envio = None
    if tipo == "credito":
        envio = enviar_nota_credito(db, nota_id)
    elif tipo == "debito":
        envio = enviar_nota_debito(db, nota_id)
    return {"ok": True, "nota_id": nota_id, "envio": envio}
