from decimal import Decimal

import uuid

from dte import generar_nota_remision_json


def test_generar_nota_remision_json_from_dte(db_conn):
    factura = {
        "identificacion": {
            "tipoDte": "01",
            "codigoGeneracion": str(uuid.uuid4()).upper(),
            "fecEmi": "2024-01-01",
        },
        "emisor": {"nombre": "Emisor"},
        "receptor": {"numDocumento": "0614-123456-102-3", "nombre": "Cliente"},
        "cuerpoDocumento": [
            {
                "numItem": 1,
                "descripcion": "Prod",
                "cantidad": 1,
                "uniMedida": 59,
            }
        ],
    }

    nr = generar_nota_remision_json(
        db_conn,
        factura,
        cantidades={1: 2},
        extension={"docuEntrega": "0614-111111-101-1", "docuRecibe": "0614-222222-102-2"},
    )

    doc_rel = nr["documentoRelacionado"][0]
    ident = factura["identificacion"]
    assert doc_rel["tipoDocumento"] == ident["tipoDte"]
    assert doc_rel["tipoGeneracion"] == 2
    assert doc_rel["numeroDocumento"] == ident["codigoGeneracion"]
    assert doc_rel["fechaEmision"] == ident["fecEmi"]

    # receptor sanitized
    assert nr["receptor"]["numDocumento"] == "06141234561023"
    # extension sanitized
    assert nr["extension"]["docuEntrega"] == "06141111111011"
    assert nr["extension"]["docuRecibe"] == "06142222221022"

    item = nr["cuerpoDocumento"][0]
    assert item["precioUni"] == 0.0
    assert item["cantidad"] == 2

    resumen = nr["resumen"]
    assert resumen["montoTotalOperacion"] == Decimal("0.00")
    assert resumen["totalNoSuj"] == Decimal("0.00")
    assert resumen["totalGravada"] == Decimal("0.00")
