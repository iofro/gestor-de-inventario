import os
import json

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

# Catálogo simplificado de tributos aplicables a los ítems del DTE
#
# Las claves corresponden a los códigos oficiales de tributo definidos por
# el Ministerio de Hacienda.  Los valores son meramente descriptivos y no se
# utilizan actualmente en la lógica; se mantienen para referencia humana.
#
# Este catálogo se utiliza para validar los campos ``codTributo`` y
# ``tributos`` dentro del ``cuerpoDocumento``.
TRIBUTOS = {
    "20": "IVA 13%",
    "A8": "Percepción a sujetos excluidos",
    "57": "Renta",
    "90": "IVA retenido",
    "D4": "IEPES",
    "D5": "IVA",
    "25": "Fovial",
    "A6": "CESC",
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


def get_dte_schema(tipo: str) -> dict | None:
    """Return the JSON schema dictionary for ``tipo``.

    ``tipo`` debe ser un código de DTE como ``"01"`` o ``"03"``.  Si no se
    encuentra un esquema asociado o el archivo no existe, devuelve ``None``.
    """
    path = SCHEMA_MAP.get(tipo)
    if not path or not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)

