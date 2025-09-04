import fitz
import json
from pathlib import Path
from shutil import copyfile

import dte as dte_module
from svfe import config as svfe_config
from db import DB
from notas import generar_nota_credito_json
from factura_sv import generar_nota_credito_pdf


def create_db():
    return DB(":memory:")


def _setup_datos_negocio(tmp_path: Path):
    dest = tmp_path / "datos_negocio.json"
    src = Path("datos_negocio.json")
    if src.exists():
        copyfile(src, dest)
    else:
        dest.write_text(
            json.dumps(
                {
                    "nit": "00000000000000",
                    "nrc": "000000-0",
                    "nombre": "Empresa",
                    "nombreComercial": "Empresa",
                    "codActividad": "46484",
                    "descActividad": "Pruebas",
                    "telefono": "2222",
                    "correo": "test@example.com",
                    "direccion": {
                        "departamento": "01",
                        "municipio": "10",
                        "complemento": "X",
                    },
                },
                ensure_ascii=False,
            )
        )
    dte_module.DATOS_NEGOCIO_PATH = str(dest)
    svfe_config.DATOS_NEGOCIO_PATH = str(dest)


def test_generar_nota_credito_json_ticket(tmp_path):
    db = create_db()
    db.add_vendedor("V1")
    vid = db.cursor.lastrowid
    db.add_producto("Prod", "P1", None,  vid, None, 0, 0, 0, 10)
    pid = db.cursor.lastrowid
    venta_id = db.add_venta("2024-01-01", 10)
    db.add_detalle_venta(venta_id, pid, 1, 10, vendedor_id=vid)
    db.cursor.execute(
        "INSERT INTO notas (venta_id, tipo, fecha, monto, motivo) VALUES (?,?,?,?,?)",
        (venta_id, "credito", "2024-01-02", 10, "Dev"),
    )
    nota_id = db.cursor.lastrowid
    db.conn.commit()

    _setup_datos_negocio(tmp_path)
    data = generar_nota_credito_json(db, nota_id)
    assert data["identificacion"]["tipoDte"] == "05"
    assert isinstance(data.get("documentoRelacionado"), list)
    rel = data["documentoRelacionado"][0]
    assert rel["tipoDocumento"] == "03"
    assert rel["tipoGeneracion"] == 2
    assert data["cuerpoDocumento"][0]["precioUni"] > 0
    assert data["resumen"]["montoTotalOperacion"] > 0
    assert "totalPagar" not in data["resumen"]


def test_generar_nota_credito_json_factura(tmp_path):
    db = create_db()
    db.add_vendedor("V1")
    vid = db.cursor.lastrowid
    db.add_producto("Prod", "P1", None,  vid, None, 0, 0, 0, 10)
    pid = db.cursor.lastrowid
    db.add_cliente("Cliente", "123", "06142201591023", "", "giro", "", "", "Dir", "01", "10")
    cliente_id = db.cursor.lastrowid
    venta_id = db.add_venta_credito_fiscal(
        cliente_id, "2024-01-01", 10, "123", "06142201591023", "giro", descuentos=0
    )
    db.add_detalle_venta(venta_id, pid, 1, 10, vendedor_id=vid)
    db.cursor.execute(
        "INSERT INTO notas (venta_id, tipo, fecha, monto, motivo) VALUES (?,?,?,?,?)",
        (venta_id, "credito", "2024-01-02", 10, "Dev"),
    )
    nota_id = db.cursor.lastrowid
    db.conn.commit()

    _setup_datos_negocio(tmp_path)
    data = generar_nota_credito_json(db, nota_id)
    rel = data["documentoRelacionado"][0]
    assert rel["tipoDocumento"] == "03"


def _sample_data():
    venta = {
        "sumas": 10,
        "descuentos": 0,
        "subtotal": 10,
        "iva": 1.3,
        "total": 11.3,
        "ventas_exentas": 0,
        "ventas_no_sujetas": 0,
        "total_letras": "ONCE CON 30/100 DOLARES",
    }
    detalles = [
        {
            "cantidad": 1,
            "descripcion": "Prod",
            "precio_unitario": 10,
            "ventas_no_sujetas": 0,
            "ventas_exentas": 0,
            "ventas_gravadas": 10,
        }
    ]
    return venta, detalles


def test_nota_credito_pdf(tmp_path):
    venta, detalles = _sample_data()
    out = tmp_path / "nota.pdf"
    generar_nota_credito_pdf(venta, detalles, {}, {}, archivo=str(out), datos_negocio={})
    assert out.exists()
    with fitz.open(out) as doc:
        text = "".join(p.get_text() for p in doc)
    assert "DOCUMENTO TRIBUTARIO ELECTRÓNICO" in text
    assert "NOTA DE CRÉDITO" in text
    assert "Código Generación:" in text
    assert "Número Control:" in text
    assert "Sello Recepción:" in text
    assert "Tipo Modelo:" in text
    assert "Tipo Operación:" in text
    assert "Fecha Generación:" in text
