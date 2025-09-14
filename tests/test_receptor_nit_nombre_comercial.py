from svfe import generators
from dte import validate_dte_json
import svfe.config as svfe_config


def test_receptor_nit_and_nombre_comercial_retained(db_conn):
    svfe_config.load_datos_negocio = lambda: {
        "direccion": {
            "departamento": "01",
            "municipio": "01",
            "complemento": "X",
        }
    }
    data = generators.generar_factura_fiscal(db=db_conn)
    data["receptor"]["direccion"] = {
        "departamento": "01",
        "municipio": "13",
        "complemento": "X",
    }
    # include extraneous document fields to ensure they are removed
    data["receptor"]["tipoDocumento"] = "36"
    data["receptor"]["numDocumento"] = data["receptor"].get("nit")

    validate_dte_json(data, db=db_conn)

    receptor = data["receptor"]
    assert receptor.get("nit")
    assert receptor.get("nombreComercial")
    assert "numDocumento" not in receptor
    assert "tipoDocumento" not in receptor
