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
import re

# Longitud estándar del NIT sin guiones
NIT_LENGTH = 14

# Catálogos básicos utilizados en la validación del DTE
# Ambiente de destino
AMBIENTE = {
    "00": "Modo prueba",
    "01": "Modo producción",
}

# Tipo de documento electrónico
DTE_TIPOS = {
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
TIPO_DTE = DTE_TIPOS
TIPOS_DTE = DTE_TIPOS

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

# Catálogos oficiales disponibles. Los catálogos faltantes se inicializan
# como diccionarios vacíos para que puedan ser manejados de forma uniforme en
# la UI y las validaciones.
CATALOGS: dict[str, dict] = {
    "CAT-001": AMBIENTE,
    "CAT-002": TIPO_DTE,
    "CAT-003": MODELO,
    "CAT-004": OPERACION,
    "CAT-005": CONTINGENCIA,
    "CAT-006": TRIBUTOS,
    "CAT-007": TIPO_ESTABLEC,
    "CAT-008": TIPO_ITEM,
    "CAT-009": PLAZO,
    "CAT-010": TIPO_DOC_REC,
    "CAT-016": CONDICION_OPERACION,
    "CAT-017": FORMA_PAGO,
}

# Aseguramos que todos los catálogos CAT-001 a CAT-032 existan aunque estén
# vacíos para que la UI pueda iterarlos sin lógica adicional.
for _n in range(1, 33):
    CATALOGS.setdefault(f"CAT-{_n:03d}", {})

# Catálogos que permiten ingreso manual temporalmente
MANUAL_CATALOGS = {f"CAT-{i:03d}" for i in range(12, 18)}

# Reglas simples de validación para catálogos con ingreso manual
CATALOG_PATTERNS = {
    "CAT-012": r"^\d{2}$",
    "CAT-013": r"^\d{3}$",
    "CAT-014": r"^[A-Z0-9]{1,5}$",
    "CAT-015": r"^\d{2}$",
    "CAT-016": r"^[1-3]$",
    "CAT-017": r"^\d{2}$",
}


def is_valid_code(catalog: str, code: str) -> bool:
    """Return True if ``code`` is valid for ``catalog``."""

    code = str(code)
    options = CATALOGS.get(catalog, {})
    if options and code in {str(k) for k in options.keys()}:
        return True
    if catalog in MANUAL_CATALOGS:
        pattern = CATALOG_PATTERNS.get(catalog)
        return bool(pattern and re.fullmatch(pattern, code))
    return False

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

