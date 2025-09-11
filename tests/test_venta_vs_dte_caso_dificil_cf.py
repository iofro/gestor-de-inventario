from decimal import Decimal as D

import json

from db import DB
import dte as dte_module
from dte import generar_dte_json
from utils.monto import d2, d4, d8


def create_db():
    return DB(":memory:")


def test_venta_vs_dte_caso_dificil_cf03(tmp_path):
    datos = {
        "nit": "06141990011019",
        "nrc": "12345678",
        "nombre": "Mi Negocio",
        "nombreComercial": "Mi Negocio",
        "cod_giro": "123456",
        "descActividad": "Comercio",
        "telefono": "22222222",
        "correo": "test@example.com",
        "direccion": {
            "departamento": "06",
            "municipio": "10",
            "complemento": "Calle 1",
        },
    }
    tmp_file = tmp_path / "datos_negocio.json"
    tmp_file.write_text(json.dumps(datos))
    dte_module.DATOS_NEGOCIO_PATH = str(tmp_file)
    import svfe.config as svfe_config
    svfe_config.DATOS_NEGOCIO_PATH = str(tmp_file)
    svfe_config.load_datos_negocio = lambda: datos

    db = create_db()
    db.add_vendedor("V1")
    vid = db.cursor.lastrowid
    productos = []
    for i in range(5):
        db.add_producto(f"Prod{i}", f"P{i}", None, vid, None, 0, 0, 0, 10)
        productos.append(db.cursor.lastrowid)
    db.add_cliente(
        "Cliente",
        "123",
        "06141990011019",
        "",
        "giro",
        "70000001",
        "",
        "C",
        "06",
        "01",
    )
    cid = db.cursor.lastrowid

    items = [
        {"pid": productos[0], "qty": D("1.5"), "pf_unit": D("10.12345"), "desc_pct": D("5"), "tipo": "venta gravada"},
        {"pid": productos[1], "qty": D("2.25"), "pf_unit": D("20.98765"), "desc_abs": D("1.2345"), "tipo": "venta gravada"},
        {"pid": productos[2], "qty": D("0.5"), "pf_unit": D("30.13579"), "tipo": "venta exenta"},
        {"pid": productos[3], "qty": D("3.333"), "pf_unit": D("5.55555"), "desc_pct": D("10"), "tipo": "venta no sujeta"},
        {"pid": productos[4], "qty": D("4.75"), "pf_unit": D("7.77777"), "desc_abs": D("0.8765"), "tipo": "venta gravada"},
    ]

    calcs = []
    total_pf = D("0")
    for it in items:
        pf_line = d8(it["qty"] * it["pf_unit"])
        if "desc_abs" in it:
            pf_neto = d8(pf_line - it["desc_abs"])
        elif "desc_pct" in it:
            pf_neto = d8(pf_line * (D("1") - it["desc_pct"] / D("100")))
        else:
            pf_neto = pf_line
        if pf_neto < 0:
            pf_neto = D("0")
        if it["tipo"] == "venta gravada":
            base = d4(pf_neto / D("1.13"))
            iva = d4(pf_neto - base)
        else:
            base = d4(pf_neto)
            iva = d4(pf_neto - base)
        calcs.append({
            "qty": it["qty"],
            "pf_unit": it["pf_unit"],
            "pf_line": pf_line,
            "pf_neto": pf_neto,
            "base": base,
            "iva": iva,
        })
        total_pf += pf_neto

    total_venta = d2(total_pf)
    venta_id = db.add_venta("2024-01-01", float(total_venta), cliente_id=cid, extra={"precios_incluyen_iva": True})

    for it in items:
        if "desc_abs" in it:
            desc = float(it["desc_abs"])
            desc_tipo = ""
        elif "desc_pct" in it:
            desc = float(it["desc_pct"])
            desc_tipo = "%"
        else:
            desc = 0
            desc_tipo = ""
        db.add_detalle_venta(
            venta_id,
            it["pid"],
            float(it["qty"]),
            float(it["pf_unit"]),
            descuento=desc,
            descuento_tipo=desc_tipo,
            tipo_fiscal=it["tipo"],
            vendedor_id=vid,
        )

    data = generar_dte_json(db, venta_id, tipo_dte="03")
    resumen = data["resumen"]
    assert d2(str(resumen["montoTotalOperacion"])) == total_venta

    iva_sum = d2(sum(D(str(it.get("ivaItem", 0))) for it in data["cuerpoDocumento"]))
    assert iva_sum == d2(str(resumen.get("totalIva", 0)))

    for calc, item in zip(calcs, data["cuerpoDocumento"]):
        base = item.get("ventaGravada") or item.get("ventaExenta") or item.get("ventaNoSuj")
        print(
            f"{calc['qty']}\t{calc['pf_unit']}\t{calc['pf_line']}\t{calc['pf_neto']}\t{calc['base']}\t{calc['iva']} | {base}\t{item.get('ivaItem',0)}"
        )
