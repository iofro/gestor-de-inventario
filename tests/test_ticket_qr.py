import io

import fitz
import cv2
import numpy as np
from PIL import Image

from factura_sv import build_qr_url
from ticket_pdf import generar_ticket_pdf, generar_ticket_personalizado


def _decode_qr_from_pdf(path: str) -> str:
    """Render *path* to an image and decode the QR code."""
    with fitz.open(path) as doc:
        page = doc[0]
        pix = page.get_pixmap(dpi=200)
        img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
        arr = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
        det = cv2.QRCodeDetector()
        data, _, _ = det.detectAndDecode(arr)
        return data


def test_generar_ticket_pdf_qr(tmp_path):
    dte_json = {
        "identificacion": {
            "ambiente": "01",
            "codigoGeneracion": "ABC",
            "fechaEmi": "2020-01-01",
        }
    }
    dte_data = {"dteJson": dte_json}
    venta = {"fecha": "2024-01-01", "total": 10}
    detalles = [{"descripcion": "Prod", "cantidad": 1, "precio_unitario": 10}]
    archivo = tmp_path / "t.pdf"
    generar_ticket_pdf(venta, detalles, archivo=str(archivo), dte_data=dte_data)
    url = build_qr_url(dte_json)
    assert _decode_qr_from_pdf(str(archivo)) == url
    with fitz.open(archivo) as doc:
        page = doc[0]
        assert any(l.get("uri") == url for l in page.get_links())
        text = "".join(p.get_text() for p in doc)
    assert url not in text


def test_generar_ticket_personalizado_qr(tmp_path):
    dte_json = {
        "identificacion": {
            "ambiente": "00",
            "codigoGeneracion": "XYZ",
            "fechaEmi": "2020-02-02",
        }
    }
    dte_data = {"dteJson": dte_json}
    venta = {"total": 5}
    detalles = []
    archivo = tmp_path / "p.pdf"
    generar_ticket_personalizado(venta, detalles, archivo=str(archivo), dte_data=dte_data)
    url = build_qr_url(dte_json)
    assert _decode_qr_from_pdf(str(archivo)) == url
    with fitz.open(archivo) as doc:
        page = doc[0]
        assert any(l.get("uri") == url for l in page.get_links())
        text = "".join(p.get_text() for p in doc)
    assert url not in text

