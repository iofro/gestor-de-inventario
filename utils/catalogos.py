"""Catálogos básicos para la generación y validación de DTE.

Los valores fueron extraídos de ``svfe-json-schemas/catalogos.docx`` y de
las especificaciones del Ministerio de Hacienda de El Salvador.  Estos
diccionarios se utilizan como fuente única para validar códigos en los DTE y
deben mantenerse sincronizados con los catálogos oficiales.

Cuando un catálogo no se encuentre completo en este módulo, el sistema
permitirá que el usuario ingrese manualmente el código correspondiente en la
sección del aplicativo donde aplique.
"""

import os
import json

# Longitud estándar del NIT sin guiones
NIT_LENGTH = 14

# Catálogos básicos utilizados en la validación del DTE
# Ambiente de destino
AMBIENTE = {
    "00": "Modo prueba",
    "01": "Modo producción",
}

# Tipo de documento electrónico
TIPO_DTE = {
    "01": "Factura",
    "03": "Comprobante de crédito fiscal",
    "04": "Nota de remisión",
    "05": "Nota de crédito",
    "06": "Nota de débito",
    "07": "Comprobante de retención",
    "08": "Comprobante de liquidación",
    "09": "Documento contable de liquidación",
    "11": "Facturas de exportación",
    "14": "Factura de sujeto excluido",
    "15": "Comprobante de donación",
}

# Compatibilidad retroactiva
TIPOS_DTE = TIPO_DTE

# Modelo de facturación
MODELO = {
    1: "Previo",
    2: "Diferido",
}

# Compatibilidad retroactiva
MODELOS_FACTURACION = MODELO

# Tipo de transmisión/operación
OPERACION = {
    1: "Normal",
    2: "Contingencia",
}

# Motivos de contingencia
CONTINGENCIA = {
    1: "No disponibilidad de sistema del MH",
    2: "No disponibilidad de sistema del emisor",
    3: "Falla en servicio de Internet del emisor",
    4: "Falla en energía eléctrica del emisor",
    5: "Otro",
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
    "19": "IVA 13%",
    "A8": "IVA 13%",
    "57": "Renta",
    "90": "IVA retenido",
    "D4": "IEPES",
    "D5": "IVA",
    "25": "Fovial",
    "A6": "CESC",
}

# Tipo de establecimiento
TIPO_ESTABLEC = {
    "01": "Sucursal",
    "02": "Casa Matriz",
    "04": "Bodega",
    "07": "Patio",
}

# Tipo de ítem
TIPO_ITEM = {
    1: "Bienes",
    2: "Servicios",
    3: "Ambos",
    4: "Otros tributos por ítem",
}

# Plazo para pagos a crédito
PLAZO = {
    "01": "Días",
    "02": "Meses",
    "03": "Años",
}

# Tipo de documento del receptor
TIPO_DOC_REC = {
    "36": "NIT",
    "13": "DUI",
    "37": "Otro",
    "03": "Pasaporte",
    "02": "Carnet de Residente",
    "00": "Sin documento",
}

# Condición de operación
CONDICION_OPERACION = {
    1: "contado",
    2: "crédito",
    3: "otras",
}

# Formas de pago comunes (personalizable)
FORMA_PAGO = {
    "01": "Efectivo",
    "02": "Cheque",
    "03": "Transferencia",
    "04": "Tarjeta",
}

# Catálogos incompletos: para estos códigos el sistema solicita ingreso manual
# del usuario en las secciones correspondientes.
CATALOGOS_INCOMPLETOS = {
    "CAT-012": "Departamento",
    "CAT-013": "Municipio",
    "CAT-014": "Unidad de Medida",
    "CAT-019": "Actividad Económica",
    "CAT-020": "País",
    "CAT-021": "Otros Documentos Asociados",
    "CAT-023": "Tipo de Documento en Contingencia",
    "CAT-024": "Tipo de Invalidación",
    "CAT-025": "Título de remisión de bienes",
    "CAT-026": "Tipo de Donación",
    "CAT-027": "Recinto fiscal",
    "CAT-028": "Régimen",
    "CAT-029": "Tipo de persona",
    "CAT-030": "Transporte",
    "CAT-031": "INCOTERMS",
    "CAT-032": "Domicilio Fiscal",
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

