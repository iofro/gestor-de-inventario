"""Catálogos oficiales usados en la generación y validación de DTE.

Los diccionarios expuestos en este módulo se construyen a partir de la lista
en texto plano proporcionada por el MH.  Algunos catálogos todavía se
consideran incompletos y únicamente se registran en ``CATALOGOS_INCOMPLETOS``
para futura captura desde la interfaz de usuario.
"""

from __future__ import annotations

import json
import os
import re
from typing import Dict

# ---------------------------------------------------------------------------
# Parser básico de catálogos
# ---------------------------------------------------------------------------

_RAW_CATALOG_DATA = """
CAT-001 Ambiente de Destino
CódigoValores
00Modo prueba
01Modo producción
CAT-002 Tipo de Documento
CódigoValores
01Factura
03Comprobante de crédito fiscal
04Nota de remisión
05Nota de crédito
06Nota de débito
07Comprobante de retención
08Comprobante de liquidación
09Documento contable de liquidación
11Facturas de exportación
14Factura de sujeto excluido
15Comprobante de donación
CAT-003 Modelo de Facturación
CódigoValores
1Modelo Facturación previo
2Modelo Facturación diferido
CAT-004 Tipo de Transmisión
CódigoValores
1Transmisión normal
2Transmisión por contingencia
CAT-005 Tipo de Contingencia
CódigoValores
1No disponibilidad de sistema del MH
2No disponibilidad de sistema del emisor
3Falla en servicio de Internet del emisor
4Falla en energía eléctrica del emisor
5Otro (máx. 500 caracteres explicando motivo)
CAT-006 Retención IVA MH
CódigoValores
22Retención IVA 1%
C4Retención IVA 15%
C9Otras Retenciones IVA casos especiales
CAT-007 Tipo de Generación del Documento
CódigoValores
1Físico
2Electrónico
CAT-008
CódigoValores
N/ACatálogo eliminado
CAT-009 Tipo de Establecimiento
CódigoValores
01Sucursal
02Casa Matriz
04Bodega
07Patio
CAT-010 Código Tipo de Servicio (Médico)
CódigoValores
1Cirugía
2Operación
3Tratamiento médico
4Cirugía instituto salvadoreño de Bienestar Magisterial
5Operación instituto salvadoreño de Bienestar Magisterial
6Tratamiento médico instituto salvadoreño de Bienestar Magisterial
CAT-011 Tipo de Item
CódigoValores
1Bienes
2Servicios
3Ambos (Bienes y Servicios)
4Otros tributos por item
CAT-012 Departamento
00Otro (Para extranjeros)
01Ahuachapán
02Santa Ana
03Sonsonate
04Chalatenango
05La Libertad
06San Salvador
07Cuscatlán
08La Paz
09Cabañas
10San Vicente
11Usulután
12San Miguel
13Morazán
14La Unión
CAT-013 Municipio
00Otro (Para extranjeros)
13AHUACHAPAN NORTE
14AHUACHAPAN CENTRO
15AHUACHAPAN SUR
14SANTA ANA NORTE
15SANTA ANA CENTRO
16SANTA ANA ESTE
17SANTA ANA OESTE
17SONSONATE NORTE
18SONSONATE CENTRO
19SONSONATE ESTE
20SONSONATE OESTE
34CHALATENANGO NORTE
35CHALATENANGO CENTRO
36CHALATENANGO SUR
23LA LIBERTAD NORTE
24LA LIBERTAD CENTRO
25LA LIBERTAD OESTE
26LA LIBERTAD ESTE
27LA LIBERTAD COSTA
28LA LIBERTAD SUR
20SAN SALVADOR NORTE
21SAN SALVADOR OESTE
22SAN SALVADOR ESTE
23SAN SALVADOR CENTRO
24SAN SALVADOR SUR
17CUSCATLAN NORTE
18CUSCATLAN SUR
23LA PAZ OESTE
24LA PAZ CENTRO
25LA PAZ ESTE
10CABANAS OESTE
11CABANAS ESTE
14SAN VICENTE NORTE
15SAN VICENTE SUR
24USULUTAN NORTE
25USULUTAN ESTE
26USULUTAN OESTE
21SAN MIGUEL NORTE
22SAN MIGUEL CENTRO
23SAN MIGUEL OESTE
27MORAZAN NORTE
28MORAZAN SUR
19LA UNION NORTE
20LA UNION SUR
CAT-014 Unidad de Medida
CódigoValores
1metro
2Yarda
6milímetro
9kilómetro cuadrado
10Hectárea
13metro cuadrado
15Vara cuadrada 2
18metro cúbico
20Barril
22Galón 4
23Litro
24Botella
26Mililitro
30Tonelada
32Quintal
33Arroba
34Kilogramo
36Libra
37Onza troy 5
38Onza
39Gramo
40Miligramo
42Megawatt
43Kilowatt
44Watt
45Megavoltio-amperio
46Kilovoltio-amperio
47Voltio-amperio
49Gigawatt-hora
50Megawatt-hora
51Kilowatt-hora
52Watt-hora
53Kilovoltio
54Voltio
55Millar
56Medio millar
57Ciento
58Docena
59Unidad
99Otra 6
CAT-015 Tributos
1TRIBUTOS APLICADOS POR ÍTEMS REFLEJADOS EN EL RESUMEN DEL DTE
20Impuesto al Valor Agregado 13%
C3Impuesto al Valor Agregado (exportaciones) 0%
59Turismo por alojamiento (5%)
71Turismo salida del país por vía aérea $7.00
D1FOVIAL ($0.20 Ctv. por galón)
C8COTRANS ($0.10 Ctvs. por galón)
D5Otras tasas casos especiales
D4Otros impuestos casos especiales
2TRIBUTOS APLICADOS POR ÍTEMS REFLEJADOS EN EL CUERPO DEL DOCUMENTO
A8Impuesto Especial al Combustible (0%, 0.5%, 1%)
57Impuesto industria de Cemento
90Impuesto especial a la primera matrícula
D4Otros impuestos casos especiales
D5Otras tasas casos especiales
A6Impuesto ad-valorem armas de fuego municiones explosivas y artículos similares
3IMPUESTOS AD-VALOREM APLICADOS POR ÍTEM DE USO INFORMATIVO REFLEJADOS EN EL RESUMEN DEL DOCUMENTO
C5Impuesto ad-valorem por diferencial de precios de bebidas alcohólicas (8%)
C6Impuesto ad-valorem por diferencial de precios al tabaco cigarrillos (39%)
C7Impuesto ad-valorem por diferencial de precios al tabaco cigarros (100%)
19Fabricante de Bebidas Gaseosas Isotónicas Deportivas Fortificantes Energizante o Estimulante
28Importador de Bebidas Gaseosas Isotónicas Deportivas Fortificantes Energizante o Estimulante
31Detallistas o Expendedores de Bebidas Alcohólicas
32Fabricante de Cerveza
33Importador de Cerveza
34Fabricante de Productos de Tabaco
35Importador de Productos de Tabaco
36Fabricante de Armas de Fuego Municiones y Artículos Similares
37Importador de Arma de Fuego Munición y Artículos Similares
38Fabricante de Explosivos
39Importador de Explosivos
42Fabricante de Productos Pirotécnicos
43Importador de Productos Pirotécnicos
44Productor de Tabaco
50Distribuidor de Bebidas Gaseosas Isotónicas Deportivas Fortificantes Energizante o Estimulante
51Bebidas Alcohólicas
52Cerveza
53Productos del Tabaco
54Bebidas Carbonatadas o Gaseosas Simples o Endulzadas
55Otros Específicos
58Alcohol
77Importador de Jugos Néctares Bebidas con Jugo y Refrescos
78Distribuidor de Jugos Néctares Bebidas con Jugo y Refrescos
79Sobre Llamadas Telefónicas Provenientes del Ext.
85Detallista de Jugos Néctares Bebidas con Jugo y Refrescos
86Fabricante de Preparaciones Concentradas o en Polvo para la Elaboración de Bebidas
91Fabricante de Jugos Néctares Bebidas con Jugo y Refrescos
92Importador de Preparaciones Concentradas o en Polvo para la Elaboración de Bebidas
A1Específicos y Ad-Valorem
A5Bebidas Gaseosas Isotónicas Deportivas Fortificantes Energizantes o Estimulantes
A7Alcohol Etílico
A9Sacos Sintéticos
CAT-016 Condición de la Operación
1Contado
2A crédito
3Otro
CAT-017 Forma de Pago
01Billetes y monedas
02Tarjeta Débito
03Tarjeta Crédito
04Cheque
05Transferencia-Depósito Bancario
08Dinero electrónico
09Monedero electrónico
11Bitcoin
12Otras Criptomonedas
13Cuentas por pagar del receptor
14Giro bancario
99Otros (se debe indicar el medio de pago)
CAT-018 Plazo
CódigoValores
01Días
02Meses
03Años
CAT-019 Código de Actividad Económica
AGRICULTURA, GANADERÍA, SILVICULTURA Y PESCA
PRODUCCIÓN AGRÍCOLA, PECUARIA, CAZA Y ACTIVIDADES DE SERVICIOS CONEXAS
CÓDIGOACTIVIDADES ECONÓMICAS
01111Cultivo de cereales excepto arroz y para forrajes
01112Cultivo de legumbres
01113Cultivo de semillas oleaginosas
01114Cultivo de plantas para la preparación de semillas
01119Cultivo de otros cereales excepto arroz y forrajeros n.c.p.
01120Cultivo de arroz
01131Cultivo de raíces y tubérculos
…..
CAT-020 País
Código – Valores
AF – Afganistán
AX – Aland
AL – Albania
DE – Alemania
AD – Andorra
AO – Angola
AI – Anguila
AQ – Antártica
AG – Antigua y Barbuda
AW – Aruba
SA – Arabia Saudita
DZ – Argelia
AR – Argentina
AM – Armenia
DJ – Djibouti
EC – Ecuador
EG – Egipto
SV – El Salvador
AE – Emiratos Árabes Unidos
ER – Eritrea
SK – Eslovaquia
SI – Eslovenia
ES – España
US – Estados Unidos
EE – Estonia
ET – Etiopía
FJ – Fiji
PH – Filipinas
FI – Finlandia
FR – Francia
GA – Gabón
GM – Gambia
GE – Georgia
GH – Ghana
GI – Gibraltar
GD – Granada
GR – Grecia
GL – Groenlandia
GP – Guadalupe
GU – Guam
GT – Guatemala
GF – Guayana Francesa
GG – Guernsey
GN – Guinea
GQ – Guinea Ecuatorial
GW – Guinea-Bissau
GY – Guyana
HT – Haití
HN – Honduras
HK – Hong Kong
HU – Hungría
IN – India
ID – Indonesia
IQ – Irak
IE – Irlanda
BV – Isla Bouvet
IM – Isla de Man
CAT-021 Otros Documentos Asociados
Código – Valores
1 – Emisor
2 – Receptor
3 – Médico (solo aplica para contribuyentes obligados a la presentación de F-958)
4 – Transporte (solo aplica para Factura de exportación)
CAT-022 Tipo de documento de identificación del Receptor
Código – Valores
36 – NIT
13 – DUI
37 – Otro
03 – Pasaporte
02 – Carnet de Residente
CAT-023 Tipo de Documento en Contingencia
Código – Valores
01 – Factura Electrónico
03 – Comprobante de Crédito Fiscal Electrónico
04 – Nota de Remisión Electrónica
05 – Nota de Crédito Electrónica
06 – Nota de Débito Electrónica
11 – Factura de Exportación Electrónica
14 – Factura de Sujeto Excluido Electrónica
CAT-024 Tipo de Invalidación
Código – Valores
1 – Error en la Información del Documento Tributario Electrónico a invalidar
2 – Rescindir de la operación realizada
3 – Otro
CAT-025 Título a que se remiten los bienes
Código – Valores
01 – Depósito
02 – Propiedad
03 – Consignación
04 – Traslado
05 – Otros
CAT-026 Tipo de Donación
Código – Valores
1 – Efectivo
2 – Bien
3 – Servicio
CAT-027 Recinto fiscal
Código – Valores
01 – Terrestre San Bartolo
02 – Marítima de Acajutla
03 – Aérea De Comalapa
04 – Terrestre Las Chinamas
05 – Terrestre La Hachadura
06 – Terrestre Santa Ana
07 – Terrestre San Cristóbal
08 – Terrestre Anguiatú
09 – Terrestre El Amatillo
10 – Marítima La Unión
11 – Terrestre El Poy
12 – Terrestre Metapán
15 – Fardos Postales
16 – Z.F. San Marcos
17 – Z.F. El Pedregal
18 – Z.F. San Bartolo
20 – Z.F. Exportsalva
21 – Z.F. American Park
23 – Z.F. Internacional
24 – Z.F. Diez
26 – Z.F. Miramar
27 – Z.F. Santo Tomas
28 – Z.F. Santa Tecla
29 – Z.F. Santa Ana
30 – Z.F. La Concordia
31 – Aérea Ilopango
32 – Z.F. Pipil
33 – Puerto Barillas
34 – Z.F. Calvo Conservas
35 – Feria Internacional
36 – Aduana El Papalón
37 – Z.F. Sam-Li
38 – Z.F. San José
39 – Z.F. Las Mercedes
71 – Aldesa
72 – Agdosa Merliot
73 – Bodesa
76 – Delegacion DHL
77 – Transauto
80 – Nejapa
81 – Almaconsa
83 – Agdosa Apopa
85 – Gutiérrez Courier Y Cargo
99 – San Bartolo Envio Hn/Gt
CAT-028 Régimen
Código – Valores
EX-1.1000.000 – Exportación Definitiva, Exportación Definitiva, Régimen Común
EX-1.1040.000 – Exportación Definitiva, Sustitución de Mercancías, Régimen Común
EX-1.1041.020 – Exportación Definitiva, Proveniente de Franquicia Provisional, Frang. Presidenciales exento de DAI
EX-1.1041.021 – Exportación Definitiva, Proveniente de Franquicia Provisional, Frang. Presidenciales exento de DAI e IVA
EX-1.1048.025 – Exportación Definitiva, Proveniente de Franquicia Definitiva, Maquinaria y Equipo LZF. DPA
EX-1.1048.031 – Exportación Definitiva, Proveniente de Franquicia Definitiva, Distribución Internacional
CAT-029 Tipo de persona
Código – Valores
1 – Persona Natural
2 – Persona Jurídica
CAT-030 Transporte
Código – Valores
1 – TERRESTRE
2 – AÉREO
3 – MARÍTIMO
4 – FERREO
5 – MULTIMODAL
6 – CORREO
CAT-031 INCOTERMS
Código – Valores
01 – EXW-En fábrica
02 – FCA-Libre transportista
03 – CPT-Transporte pagado hasta
04 – CIP-Transporte y seguro pagado hasta
05 – DAP-Entrega en el lugar
06 – DPU-Entregado en el lugar descargado
07 – DDP-Entrega con impuestos pagados
08 – FAS-Libre al costado del buque
09 – FOB-Libre a bordo
10 – CFR-Costo y flete
11 – CIF-Costo seguro y flete
CAT-032 Domicilio Fiscal
Código – Valores
1 – Domiciliado
2 – No Domiciliado
"""


def _parse_raw_catalogs(text: str) -> tuple[Dict[str, Dict[str, str]], Dict[str, str]]:
    """Parse raw catalog text into dictionaries and mark incompletes."""

    catalogs: Dict[str, Dict[str, str]] = {}
    names: Dict[str, str] = {}
    incompletos: set[str] = set()
    current: str | None = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        line = line.replace("–", "-")
        m = re.match(r"(CAT-\d{3})\s+(.*)", line)
        if m:
            current = m.group(1)
            names[current] = m.group(2).strip()
            catalogs[current] = {}
            continue
        if current is None:
            continue
        if line.lower().startswith("codigo") or line.lower().startswith("código"):
            continue
        if "…" in line or "..." in line:
            incompletos.add(current)
            continue
        i = 0
        while i < len(line) and (line[i].isalnum() or line[i] in ".-"):
            if i > 0 and line[i].isalpha() and line[i - 1].isdigit():
                break
            i += 1
        code = line[:i].upper()
        label = line[i:].strip().lstrip('-').lstrip('–').strip()
        if not code or not label:
            continue
        if current == "CAT-015" and code in {"1", "2", "3"} and label.upper().startswith(("TRIBUTOS", "IMPUESTOS")):
            continue
        catalogs[current][code] = label

    # Catálogos marcados manualmente como incompletos
    manual_incompletos = {"CAT-008", "CAT-013", "CAT-019", "CAT-020"}

    complete: Dict[str, Dict[str, str]] = {}
    incompletos_map: Dict[str, str] = {}
    for key, values in catalogs.items():
        if not values or key in incompletos or key in manual_incompletos:
            incompletos_map[key] = names.get(key, "")
        else:
            complete[key] = values

    for key in manual_incompletos:
        incompletos_map.setdefault(key, names.get(key, ""))
    incompletos_map["CAT-008"] = "Catálogo eliminado"

    return complete, incompletos_map


_CATS, CATALOGOS_INCOMPLETOS = _parse_raw_catalogs(_RAW_CATALOG_DATA)


# ---------------------------------------------------------------------------
# Constantes públicas
# ---------------------------------------------------------------------------

# Longitud estándar del NIT sin guiones
NIT_LENGTH = 14

# Catálogos completos específicos usados de forma directa
AMBIENTE = _CATS["CAT-001"]
DTE_TIPOS = _CATS["CAT-002"]

# Compatibilidad retroactiva
TIPO_DTE = DTE_TIPOS
TIPOS_DTE = DTE_TIPOS

MODELO = {int(k): v for k, v in _CATS["CAT-003"].items()}
MODELOS_FACTURACION = MODELO

OPERACION = {int(k): v for k, v in _CATS["CAT-004"].items()}
CONTINGENCIA = {int(k): v for k, v in _CATS["CAT-005"].items()}

TRIBUTOS = _CATS["CAT-015"].copy()
TRIBUTO_IVA = "20"
TRIBUTOS.setdefault(TRIBUTO_IVA, "Impuesto al Valor Agregado 13%")

TIPO_ESTABLEC = _CATS["CAT-009"]
TIPO_ITEM = {int(k): v for k, v in _CATS["CAT-011"].items()}

PLAZO = _CATS["CAT-018"]

TIPO_DOC_REC = _CATS["CAT-022"].copy()
TIPO_DOC_REC.setdefault("00", "Sin documento")

CONDICION_OPERACION = {int(k): v for k, v in _CATS["CAT-016"].items()}

FORMA_PAGO = _CATS["CAT-017"]

# Conjuntos derivados
TRIBUTOS_PERMITIDOS_RESUMEN = set(TRIBUTOS.keys())
TRIBUTOS_PERMITIDOS_ITEM = set(TRIBUTOS.keys())

# Mapa general de catálogos para acceso dinámico
CATALOGS: Dict[str, Dict[str, str]] = {key: val for key, val in _CATS.items()}
CATALOGS["TRIBUTOS"] = TRIBUTOS
CATALOGS["TIPO_ITEM"] = {str(k): v for k, v in TIPO_ITEM.items()}


# ---------------------------------------------------------------------------
# Esquemas JSON oficiales
# ---------------------------------------------------------------------------

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
    """Retorna el esquema JSON asociado al ``tipo`` de DTE."""

    path = SCHEMA_MAP.get(tipo)
    if not path or not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# Utilidades para acceso dinámico a catálogos
# ---------------------------------------------------------------------------

def get_value(cat: str, code: str, default: str | None = None) -> str | None:
    """Devuelve la descripción asociada a ``code`` en ``cat``."""

    return CATALOGS.get(cat, {}).get(code, default)


def validate_code(cat: str, code: str) -> bool:
    """Indica si ``code`` existe dentro del catálogo ``cat``."""

    return code in CATALOGS.get(cat, {})


def list_codes(cat: str) -> list[str]:
    """Lista los códigos disponibles para ``cat``."""

    return list(CATALOGS.get(cat, {}).keys())


def register_code(cat: str, code: str, label: str) -> None:
    """Permite registrar dinámicamente un nuevo código en ``cat``."""

    code = str(code).upper()
    dest = CATALOGS.setdefault(cat, {})
    dest[code] = label
    if cat == "TRIBUTOS":
        TRIBUTOS[code] = label
        TRIBUTOS_PERMITIDOS_RESUMEN.add(code)
        TRIBUTOS_PERMITIDOS_ITEM.add(code)
    elif cat == "TIPO_ITEM":
        try:
            TIPO_ITEM[int(code)] = label
        except ValueError:
            pass

