import os

# Longitud estándar del NIT sin guiones
NIT_LENGTH = 14

# Catálogos básicos utilizados en la validación del DTE
TIPOS_DTE = {
    "01": "Factura",
    "03": "Comprobante de Crédito Fiscal",
    "04": "Nota de Remisión",
    "05": "Nota de Crédito",
    "06": "Nota de Débito",
}

MODELOS_FACTURACION = {
    1: "Facturación previo",
    2: "Facturación posterior",
}

# Mapa de esquemas oficiales por tipo de documento
ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
SCHEMAS_DIR = os.path.join(ROOT_DIR, "svfe-json-schemas")
SCHEMA_MAP = {
    "01": os.path.join(SCHEMAS_DIR, "fe-fc-v1.json"),
    "03": os.path.join(SCHEMAS_DIR, "fe-ccf-v3.json"),
    "04": os.path.join(SCHEMAS_DIR, "fe-nr-v3.json"),
    "05": os.path.join(SCHEMAS_DIR, "fe-nc-v3.json"),
    "06": os.path.join(SCHEMAS_DIR, "fe-nd-v3.json"),
}
