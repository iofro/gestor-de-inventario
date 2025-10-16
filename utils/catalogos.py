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
import unicodedata
import warnings
from typing import Dict

from utils import resource_path

# ---------------------------------------------------------------------------
# Parser básico de catálogos
# ---------------------------------------------------------------------------

_RAW_CATALOG_DATA = """
CAT-001 Ambiente de destino
Código	Valores
00	Modo prueba
01	Modo producción
CAT-002 Tipo de Documento
Código	Valores
01	Factura
03	Comprobante de crédito fiscal
04	Nota de remisión
05	Nota de crédito
06	Nota de débito
07	Comprobante de retención
08	Comprobante de liquidación
09	Documento contable de liquidación
11	Facturas de exportación
14	Factura de sujeto excluido
15	Comprobante de donación
CAT-003 Modelo de Facturación
Código	Valores
1	Modelo Facturación previo
2	Modelo Facturación diferido
CAT-004 Tipo de Transmisión
Código	Valores
1	Transmisión normal
2	Transmisión por contingencia
CAT-005 Tipo de Contingencia
Código	Valores
1	No disponibilidad de sistema del MH
2	No disponibilidad de sistema del emisor
3	Falla en el suministro de servicio de Internet del Emisor
4	Falla en el suministro de servicio de energía eléctrica del emisor que impida la transmisión de los DTE
5	Otro (deberá digitar un máximo de 500 caracteres explicando el motivo)
CAT-006 Retención IVA MH
Código	Valores
22	Retención IVA 1%
C4	Retención IVA 13%
C9	Otras retenciones IVA casos especiales
CAT-007 Tipo de Generación del Documento
Código	Valores
1	Físico
2	Electrónico
CAT-008
Código	Valores
N/A	Catálogo eliminado
CAT-009 Tipo de establecimiento
Código	Valores
01	Sucursal
02	Casa Matriz
04	Bodega
07	Patio
CAT-010 Código tipo de Servicio (Médico)
Código	Valores
1	Cirugía
2	Operación
3	Tratamiento médico
4	Cirugía instituto salvadoreño de Bienestar Magisterial
5	Operación Instituto Salvadoreño de Bienestar Magisterial
6	Tratamiento médico Instituto Salvadoreño de Bienestar Magisterial
CAT-011 Tipo de ítem
Código	Valores
1	Bienes
2	Servicios
3	Ambos (Bienes y Servicios, incluye los dos inherente a los Productos o servicios)
4	Otros tributos por ítem
CAT-012 Departamento
Código	Valores
00	Otro (Para extranjeros)
01	Ahuachapán
02	Santa Ana
03	Sonsonate
04	Chalatenango
05	La Libertad
06	San Salvador
07	Cuscatlán
08	La Paz
09	Cabañas
10	San Vicente
11	Usulután
12	San Miguel
13	Morazán
14	La Unión
CAT-013 Municipio
Código	Valores
00	Otro (Para extranjeros)
13	AHUACHAPAN NORTE
14	AHUACHAPAN CENTRO
15	AHUACHAPAN SUR
14	SANTA ANA NORTE
15	SANTA ANA CENTRO
16	SANTA ANA ESTE
17	SANTA ANA OESTE
17	SONSONATE NORTE
18	SONSONATE CENTRO
19	SONSONATE ESTE
20	SONSONATE OESTE
34	CHALATENANGO NORTE
35	CHALATENANGO CENTRO
36	CHALATENANGO SUR
23	LA LIBERTAD NORTE
24	LA LIBERTAD CENTRO
25	LA LIBERTAD OESTE
26	LA LIBERTAD ESTE
27	LA LIBERTAD COSTA
28	LA LIBERTAD SUR
20	SAN SALVADOR NORTE
21	SAN SALVADOR OESTE
22	SAN SALVADOR ESTE
23	SAN SALVADOR CENTRO
24	SAN SALVADOR SUR
17	CUSCATLAN NORTE
18	CUSCATLAN SUR
23	LA PAZ OESTE
24	LA PAZ CENTRO
25	LA PAZ ESTE
10	CABAÑAS OESTE
11	CABAÑAS ESTE
14	SAN VICENTE NORTE
15	SAN VICENTE SUR
24	USULUTAN NORTE
25	USULUTAN ESTE
26	USULUTAN OESTE
21	SAN MIGUEL NORTE
22	SAN MIGUEL CENTRO
23	SAN MIGUEL OESTE
27	MORAZAN NORTE
28	MORAZAN SUR
19	LA UNION NORTE
20	LA UNION SUR
CAT-014 Unidad de Medida
Código	Valores
1	metro
2	Yarda 1
6	milímetro
9	kilómetro cuadrado
10	Hectárea
13	metro cuadrado
15	Vara cuadrada 2
18	metro cúbico
20	Barril 3
22	Galón 1, 4
23	Litro
24	Botella 
26	Mililitro
30	Tonelada
32	Quintal 1
33	Arroba 1
34	Kilogramo
36	Libra 1
37	Onza troy 5
38	Onza 1
39	Gramo
40	Miligramo
42	Megawatt
43	Kilowatt
44	Watt
45	Megavoltio-amperio
46	Kilovoltio-amperio
47	Voltio-amperio
49	Gigawatt-hora
50	Megawatt-hora
51	Kilowatt-hora
52	Watt-hora
53	Kilovoltio
54	Voltio
55	Millar
56	Medio millar
57	Ciento
58	Docena
59	Unidad
99	Otra 6
* Notas CAT-014
* 1: Unidad de medida que se utilizará según el Reglamento Técnico Salvadoreño RTS. 01.02.01:18 Metrología (SI).
* 2: Unidad de medida dejará de utilizarse con la entrada en vigencia del Reglamento Técnico Salvadoreño RTS. 01.02.01:18 Metrología (SI).
* 3: Aplica solo para productos derivados del petróleo.
* 4: Se refiere al Galón USA.
* 5: Medida aplica solo para tipo de bien oro.
* 6: Utilizada para detallar formas de presentación del producto
CAT-015 Tributos
* TRIBUTOS APLICADOS POR ÍTEMS REFLEJADOS EN EL RESUMEN DEL DTE
20	Impuesto al Valor Agregado 13%
C3	Impuesto al Valor Agregado (exportaciones) 0% 
59	Turismo: por alojamiento (5%)
71	Turismo: salida del país por vía aérea $7.00
D1	FOVIAL ($0.20 Ctvs. por galón)
C8	COTRANS ($0.10 Ctvs. por galón)
D5	Otras tasas casos especiales
D4	Otros impuestos casos especiales
* TRIBUTOS APLICADOS POR ÍTEMS REFLEJADOS EN EL CUERPO DEL DOCUMENTO
A8	Impuesto Especial al Combustible (0%, 0.5%, 1%)
57	Impuesto industria de Cemento 
90	Impuesto especial a la primera matrícula
D4	Otros impuestos casos especiales
D5	Otras tasas casos especiales
A6	Impuesto ad- valorem, armas de fuego, municiones explosivas y artículos similares
* IMPUESTOS AD-VALOREM APLICADOS POR ÍTEM DE USO INFORMATIVO REFLEJADOS EL RESUMEN DEL DOCUMENTO
C5	 Impuesto ad- valorem por diferencial de precios de bebidas alcohólicas (8%)
C6	 Impuesto ad- valorem por diferencial de precios al tabaco cigarrillos (39%)
C7	 Impuesto ad- valorem por diferencial de precios al tabaco cigarros (100%)
19	Fabricante de Bebidas Gaseosas, Isotónicas, Deportivas, Fortificantes, Energizante o Estimulante
28	Importador de Bebidas Gaseosas, Isotónicas, Deportivas, Fortificantes, Energizante o Estimulante
31	Detallistas o Expendedores de Bebidas Alcohólicas
32	Fabricante de Cerveza
33	Importador de Cerveza
34	Fabricante de Productos de Tabaco
35	Importador de Productos de Tabaco
36	Fabricante de Armas de Fuego, Municiones y Artículos Similares
37	Importador de Arma de Fuego, Munición y Artículos. Similares
38	Fabricante de Explosivos
39	Importador de Explosivos
42	Fabricante de Productos Pirotécnicos
43	Importador de Productos Pirotécnicos
44	Productor de Tabaco
50	Distribuidor de Bebidas Gaseosas, Isotónicas, Deportivas, Fortificantes, Energizante o Estimulante
51	Bebidas Alcohólicas
52	Cerveza
53	Productos del Tabaco
54	Bebidas Carbonatadas o Gaseosas Simples o Endulzadas
55	Otros Específicos
58	Alcohol
77	Importador de Jugos, Néctares, Bebidas con Jugo y Refrescos
78	Distribuidor de Jugos, Néctares, Bebidas con Jugo y Refrescos
79	Sobre Llamadas Telefónicas Provenientes del Ext.
85	Detallista de Jugos, Néctares, Bebidas con Jugo y Refrescos
86	Fabricante de Preparaciones Concentradas o en Polvo para la Elaboración de Bebidas
91	Fabricante de Jugos, Néctares, Bebidas con Jugo y Refrescos
92	Importador de Preparaciones Concentradas o en Polvo para la Elaboración de Bebidas
A1	Específicos y Ad-Valorem
A5	Bebidas Gaseosas, Isotónicas, Deportivas, Fortificantes, Energizantes o Estimulantes
A7	Alcohol Etílico
A9	Sacos Sintéticos
CAT-016 Condición de la Operación
Código	Valores
1	Contado
2	A crédito
3	Otro
CAT-017 Forma de Pago
Código	Valores
01	Billetes y monedas
02	Tarjeta Débito
03	Tarjeta Crédito
04	Cheque
05	Transferencia-Depósito Bancario
08	Dinero electrónico
09	Monedero electrónico
11	Bitcoin
12	Otras Criptomonedas
13	Cuentas por pagar del receptor
14	Giro bancario 
99	Otros (se debe indicar el medio de pago)
CAT-018 Plazo
Código	Valores
01	Días
02	Meses
03	Años
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
Código	Valores
AF	Afganistán
AX	Aland
AL	Albania
DE	Alemania
AD	Andorra
AO	Angola
AI	Anguila
AQ	Antártica
AG	Antigua y Barbuda
AW	Aruba
SA	Arabia Saudita
DZ	Argelia
AR	Argentina
AM	Armenia
AU	Australia
AT	Austria
AZ	Azerbaiyán
BS	Bahamas
BH	Bahrein
BD	Bangladesh
BB	Barbados
BE	Bélgica
BZ	Belice
BJ	Benin
BM	Bermudas
BY	Bielorrusia
BO	Bolivia
BQ	Bonaire, Sint Eustatius and Saba
BA	Bosnia-Herzegovina
BW	Botswana
BR	Brasil
BN	Brunei
BG	Bulgaria
BF	Burkina Faso
BI	Burundi
BT	Bután
CV	Cabo Verde
KY	Caimán, Islas
KH	Camboya
CM	Camerún
CA	Canadá
CF	Centroafricana, República
TD	Chad
CL	Chile
CN	China
CY	Chipre
VA	Ciudad del Vaticano
CO	Colombia
KM	Comoras
CG	Congo
CI	Costa de Marfil
CR	Costa Rica
HR	Croacia
CU	Cuba
CW	Curazao
DK	Dinamarca
DM	Dominica
DJ	Djiboutí
EC	Ecuador
EG	Egipto
SV	El Salvador
AE	Emiratos Árabes Unidos
ER	Eritrea
SK	Eslovaquia
SI	Eslovenia
ES	España
US	Estados Unidos
EE	Estonia
ET	Etiopía
FJ	Fiji
PH	Filipinas
FI	Finlandia
FR	Francia
GA	Gabón
GM	Gambia
GE	Georgia
GH	Ghana
GI	Gibraltar
GD	Granada
GR	Grecia
GL	Groenlandia
GP	Guadalupe
GU	Guam
GT	Guatemala
GF	Guayana Francesa
GG	Guernsey
GN	Guinea
GQ	Guinea Ecuatorial
GW	Guinea-Bissau
GY	Guyana
HT	Haití
HN	Honduras
HK	Hong Kong
HU	Hungría
IN	India
ID	Indonesia
IQ	Irak
IE	Irlanda
BV	Isla Bouvet
IM	Isla de Man
NF	Isla Norfolk
IS	Islandia
CX	Islas Navidad
CC	Islas Cocos
CK	Islas Cook
FO	Islas Faroe
GS	Islas Georgias d. S.-Sandwich d. S.
HM	Islas Heard y McDonald
FK	Islas Malvinas (Falkland)
MP	Islas Marianas del Norte
MH	Islas Marshall
PN	Islas Pitcairn
TC	Islas Turcas y Caicos
UM	Islas Ultramarinas de E.E.U.U
VI	Islas Vírgenes
IL	Israel
IT	Italia
JM	Jamaica
JP	Japón
JE	Jersey
JO	Jordania
KZ	Kazajistán
KE	Kenia
KG	Kirguistán
KI	Kiribati
KW	Kuwait
LA	Laos, República Democrática
LS	Lesotho
LV	Letonia
LB	Líbano
LR	Liberia
LY	Libia
LI	Liechtenstein
LT	Lituania
LU	Luxemburgo
MO	Macao
MK	Macedonia
MG	Madagascar
MY	Malasia
MW	Malawi
MV	Maldivas
ML	Malí
MT	Malta
MA	Marruecos
MQ	Martinica e.a.
MU	Mauricio
MR	Mauritania
YT	Mayotte
MX	México
FM	Micronesia
MD	Moldavia, República de
MC	Mónaco
MN	Mongolia
ME	Montenegro
MS	Montserrat
MZ	Mozambique
MM	Myanmar
NA	Namibia
NR	Nauru
NP	Nepal
NI	Nicaragua
NE	Níger
NG	Nigeria
NU	Niue
NO	Noruega
NC	Nueva Caledonia
NZ	Nueva Zelanda
OM	Omán
NL	Países Bajos
PK	Pakistán
PW	Palaos
PS	Palestina
PA	Panamá
PG	Papúa, Nueva Guinea
PY	Paraguay
PE	Perú
PF	Polinesia Francesa
PL	Polonia
PT	Portugal
PR	Puerto Rico
QA	Qatar
GB	Reino Unido
KP	Rep. Democrática popular de Corea
CZ	República Checa
KR	República de Corea
CD	República Democrática del Congo
DO	República Dominicana
IR	República Islámica de Irán
RE	Reunión
RW	Ruanda
RO	Rumania
RU	Rusia
EH	Sahara Occidental
BL	Saint Barthélemy
MF	Saint Martin (French part)
SB	Salomón, Islas
WS	Samoa
AS	Samoa Americana
KN	San Cristóbal y Nieves
SM	San Marino
PM	San Pedro y Miquelón
VC	San Vicente y las Granadinas
SH	Santa Elena
LC	Santa Lucía
ST	Santo Tomé y Príncipe
SN	Senegal
RS	Serbia
SC	Seychelles
SL	Sierra Leona
SG	Singapur
SX	Sint Maarten (Dutch part)
SY	Siria
SO	Somalia
SS	South Sudan
LK	Sri Lanka
ZA	Sudáfrica
SD	Sudán
SE	Suecia
CH	Suiza
SR	Surinám
SJ	Svalbard y Jan Mayen
SZ	Swazilandia
TH	Tailandia
TW	Taiwan, Provincia de China
TZ	Tanzania, República Unida de
TJ	Tayikistán
IO	Territorio Británico Océano Indico
TF	Territorios Australes Franceses
TL	Timor Oriental
TG	Togo
TK	Tokelau
TO	Tonga
TT	Trinidad y Tobago
TN	Túnez
TM	Turkmenistán
TR	Turquía
TV	Tuvalu
UA	Ucrania
UG	Uganda
UY	Uruguay
UZ	Uzbekistán
VU	Vanuatu
VE	Venezuela
VN	Vietnam
VG	Islas Vírgenes Británicas
WF	Wallis y Fortuna, Islas
YE	Yemen
ZM	Zambia
ZW	Zimbabue
CAT-021 Otros Documentos Asociados
Código	Valores
1	Emisor
2	Receptor
3	Médico (solo aplica para contribuyentes obligados a la presentación de F-958)
4	Transporte (solo aplica para Factura de exportación)
CAT-022 Tipo de documento de identificación del Receptor
Código	Valores
36	NIT
13	DUI
37	Otro
03	Pasaporte
02	Carnet de Residente
CAT-023 Tipo de Documento en Contingencia
Código	Valores
01	Factura Electrónico 
03	Comprobante de Crédito Fiscal Electrónico
04	Nota de Remisión Electrónica
05	Nota de Crédito Electrónica
06	Nota de Débito Electrónica
11	Factura de Exportación Electrónica
14	Factura de Sujeto Excluido Electrónica
CAT-024 Tipo de Invalidación
Código	Valores
1	Error en la Información del Documento Tributario Electrónico a invalidar.
2	Rescindir de la operación realizada.
3	Otro
CAT-025 Título a que se remiten los bienes
Código	Valores
01	Depósito 
02	Propiedad
03	Consignación
04	Traslado
05	Otros
CAT-026 Tipo de Donación
Código	Valores
1	Efectivo
2	Bien
3	Servicio
CAT-027 Recinto fiscal
Código	Valores
01	Terrestre San Bartolo
02	Marítima de Acajutla
03	Aérea De Comalapa
04	Terrestre Las Chinamas
05	Terrestre La Hachadura
06	Terrestre Santa Ana
07	Terrestre San Cristóbal
08	Terrestre Anguiatú
09	Terrestre El Amatillo
10	Marítima La Unión
11	Terrestre El Poy
12	Terrestre Metalío
15	Fardos Postales
16	Z.F. San Marcos
17	Z.F. El Pedregal
18	Z.F. San Bartolo
20	Z.F. Exportsalva
21	Z.F. American Park
23	Z.F. Internacional
24	Z.F. Diez
26	Z.F. Miramar
27	Z.F. Santo Tomas
28	Z.F. Santa Tecla
29	Z.F. Santa Ana
30	Z.F. La Concordia
31	Aérea Ilopango
32	Z.F. Pipil
33	Puerto Barillas
34	Z.F. Calvo Conservas
35	Feria Internacional
36	Aduana El Papalón
37	Z.F. Sam-Li
38	Z.F. San José
39	Z.F. Las Mercedes
40	Z.F. EMCO
41	Z.F. Gigante
71	Aldesa
72	Agdosa Merliot
73	Bodesa
76	Delegacion DHL
77	Transauto
80	Nejapa 
81	Almaconsa
83	Agdosa Apopa
85	Gutiérrez Courier Y Cargo
99	San Bartolo Envío Hn/Gt
CAT-028 Régimen
Código	Valores
EX-1.1000.000	Exportación Definitiva, Exportación Definitiva, Régimen Común
EX-1.1040.000	Exportación Definitiva, Exportación Definitiva Sustitución de Mercancías, Régimen Común
EX-1.1041.020	Exportación Definitiva, Exportación Definitiva Proveniente de Franquicia Provisional, Franq. Presidenciales exento de DAI
EX-1.1041.021	Exportación Definitiva, Exportación Definitiva Proveniente de Franquicia Provisional, Franq. Presidenciales exento de DAI e IVA
EX-1.1048.025	Exportación Definitiva, Exportación Definitiva Proveniente de Franquicia Definitiva, Maquinaria y Equipo LZF. DPA
EX-1.1048.031	Exportación Definitiva, Exportación Definitiva Proveniente de Franquicia Definitiva, Distribución Internacional
EX-1.1048.032	Exportación Definitiva, Exportación Definitiva Proveniente. de Franquicia Definitiva, Operaciones Internacionales de Logística
EX-1.1048.033	Exportación Definitiva, Exportación Definitiva Proveniente de Franquicia Definitiva, Centro Internacional de llamadas (Call Center)
EX-1.1048.034	Exportación Definitiva, Exportación Definitiva Proveniente de Franquicia Definitiva, Tecnologías de Información LSI
EX-1.1048.035	Exportación Definitiva, Exportación Definitiva Proveniente de Franquicia Definitiva, Investigación y Desarrollo LSI
EX-1.1048.036	Exportación Definitiva, Exportación Definitiva Proveniente de Franquicia Definitiva, Reparación y Mantenimiento de Embarcaciones Marítimas LSI
EX-1.1048.037	Exportación Definitiva, Exportación Definitiva Proveniente de Franquicia Definitiva, Reparación y Mantenimiento de Aeronaves LSI
EX-1.1048.038	Exportación Definitiva, Exportación Definitiva Proveniente de Franquicia Definitiva, Procesos Empresariales LSI
EX-1.1048.039	Exportación Definitiva, Exportación Definitiva Proveniente de Franquicia Definitiva, Servicios Medico-Hospitalarios LSI
EX-1.1048.040	Exportación Definitiva, Exportación Definitiva Proveniente de Franquicia Definitiva, Servicios Financieros Internacionales LSI
EX-1.1048.043	Exportación Definitiva, Exportación Definitiva Proveniente de Franquicia Definitiva, Reparación y Mantenimiento de Contenedores LSI
EX-1.1048.044	Exportación Definitiva, Exportación Definitiva Proveniente de Franquicia Definitiva, Reparación de Equipos Tecnológicos LSI
EX-1.1048.054	Exportación Definitiva, Exportación Definitiva Proveniente de Franquicia Definitiva, Atención Ancianos y Convalecientes LSI
EX-1.1048.055	Exportación Definitiva, Exportación Definitiva Proveniente de Franquicia Definitiva, Telemedicina LSI
EX-1.1048.056	Exportación Definitiva, Exportación Definitiva Proveniente de Franquicia Definitiva, Cinematografía LSI
EX-1.1052.000	Exportación Definitiva, Exportación Definitiva de DPA con origen en Compras Locales, Régimen Común
EX-1.1054.000	Exportación Definitiva, Exportación Definitiva de Zona Franca con origen en Compras Locales, Régimen Común
EX-1.1100.000	Exportación Definitiva, Exportación Definitiva de Envíos de Socorro, Régimen Común
EX-1.1200.000	Exportación Definitiva, Exportación Definitiva de Envíos Postales, Régimen Común
EX-1.1300.000	Exportación Definitiva, Exportación Definitiva Envíos que requieren despacho urgente, Régimen Común
EX-1.1400.000	Exportación Definitiva, Exportación Definitiva Courier, Régimen Común
EX-1.1400.011	Exportación Definitiva, Exportación Definitiva Courier, Muestras Sin Valor Comercial
EX-1.1400.012	Exportación Definitiva, Exportación Definitiva Courier, Material Publicitario
EX-1.1400.017	Exportación Definitiva, Exportación Definitiva Courier, Declaración de Documentos
EX-1.1500.000	Exportación Definitiva, Exportación Definitiva Menaje de casa, Régimen Común
EX-2.2100.000	Exportación Temporal, Exportación Temporal para Perfeccionamiento Pasivo, Régimen Común
EX-2.2200.000	Exportación Temporal, Exportación Temporal con Reimportación en el mismo estado, Régimen Común
EX-2.2400.000	Traslados Definitivos                                                 
EX-3.3050.000	Re-Exportación, Reexportación Proveniente de Importación Temporal, Régimen Común
EX-3.3051.000	Re-Exportación, Reexportación Proveniente de Tiendas Libres, Régimen Común
EX-3.3052.000	Re-Exportación, Reexportación Proveniente de Admisión Temporal para Perfeccionamiento Activo, Régimen Común
EX-3.3053.000	Re-Exportación, Reexportación Proveniente de Admisión Temporal, Régimen Común
EX-3.3054.000	Re-Exportación, Reexportación Proveniente de Régimen de Zona Franca, Régimen Común
EX-3.3055.000	Re-Exportación, Reexportación Proveniente de Admisión Temporal para Perfeccionamiento Activo con Garantía, Régimen Común
EX-3.3056.000	Re-Exportación, Reexportación Proveniente de Admisión Temporal Distribución Internacional Parque de Servicios, Régimen Común
EX-3.3056.057	Re-Exportación, Reexportación Proveniente de Admisión Temporal Distribución Internacional Parque de Servicios, Remisión entre Usuarios Directos del Mismo Parque de Servicios
EX-3.3056.058	Re-Exportación, Reexportación Proveniente de Admisión Temporal Distribución Internacional Parque de Servicios, Remisión entre Usuarios Directos de Diferente Parque de Servicios
EX-3.3056.072	Re-Exportación, Reexportación Proveniente de Admisión Temporal Distribución Internacional Parque de Servicios, Decreto 738 Eléctricos e Híbridos
EX-3.3057.000	Re-Exportación, Reexportación Proveniente de Admisión Temporal Operaciones Internacional de Logística Parque de Servicios, Régimen Común
EX-3.3057.057	Re-Exportación, Reexportación Proveniente de Admisión Temporal Operaciones Internacional de Logística Parque de Servicios, Remisión entre Usuarios Directos del Mismo Parque de Servicios
EX-3.3057.058	Re-Exportación, Reexportación Proveniente de Admisión Temporal Operaciones Internacional de Logística Parque de Servicios, Remisión entre Usuarios Directos de Diferente Parque de Servicios
EX-3.3058.033	Re-Exportación, Reexportación Proveniente de Admisión Temporal Centro Servicio LSI, Centro Internacional de llamadas (Call Center)
EX-3.3058.036	Re-Exportación, Reexportación Proveniente de Admisión Temporal Centro Servicio LSI, Reparación y Mantenimiento de Embarcaciones Marítimas LSI
EX-3.3058.037	Re-Exportación, Reexportación Proveniente de Admisión Temporal Centro Servicio LSI, Reparación y Mantenimiento de Aeronaves LSI
EX-3.3058.043	Re-Exportación, Reexportación Proveniente de Admisión Temporal Centro Servicio LSI, Reparación y Mantenimiento de Contenedores LSI
EX-3.3059.000	Re-Exportación, Reexportación Proveniente de Admisión Temporal Reparación de Equipo Tecnológico Parque de Servicios, Régimen Común
EX-3.3059.057	Re-Exportación, Reexportación Proveniente de Admisión Temporal Reparación de Equipo Tecnológico Parque de Servicios, Remisión entre Usuarios Directos del Mismo Parque de Servicios
EX-3.3059.058	Re-Exportación, Reexportación Proveniente de Admisión Temporal Reparación de Equipo Tecnológico Parque de Servicios, Remisión entre Usuarios Directos de Diferente Parque de Servicios
EX-3.3070.000	Re-Exportación, Reexportación Proveniente de Depósito., Régimen Común
EX-3.3070.072	Re-Exportación, Reexportación Proveniente de Depósito., Decreto 738 Eléctricos e Híbridos
EX-3.3071.000	Reexp. Prov. de Deposito.                                             
EX-3.3052.000	Reexp. Prov. de Adm Temp. para Perfeccionamiento Activo               
EX-3.3054.000	Reexp. Prov. de Regimen de Zona Franca                                
EX-3.3055.000	Reexp. Prov.de Adm.Temporal para Perfeccionamiento Activo con Garantía
EX-3.3056.000	Re-Exp. Prov.de Adm.Temporal Ley de Servi. Internacionales            
EX-3.3057.000	Reexportación Prov. de Centro de Servicio LSI                         
CAT-029 Tipo de persona
Código	Valores
1	Persona Natural
2	Persona Jurídica
CAT-030 Transporte 
Código	Valores
1	TERRESTRE
2	AÉREO
3	MARÍTIMO
4	FERREO
5	MULTIMODAL
6	CORREO
CAT-031 INCOTERMS
Código	Valores
01	EXW-En fabrica
02	FCA-Libre transportista
03	CPT-Transporte pagado hasta
04	CIP-Transporte y seguro pagado hasta
05	DAP-Entrega en el lugar
06	DPU-Entregado en el lugar descargado
07	DDP-Entrega con impuestos pagados
08	FAS-Libre al costado del buque
09	FOB-Libre a bordo
10	CFR-Costo y flete
11	CIF- Costo seguro y flete
CAT-032 Domicilio Fiscal
Código	Valores
1	Domiciliado
2	No Domiciliado
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

# Tributos especiales permitidos por ítem según CAT-015 sección 2
TRIBUTOS_POR_ITEM_ESPECIALES = {"A8", "57", "90", "D4", "D5", "A6"}

TIPO_ESTABLEC = _CATS["CAT-009"]
TIPO_ITEM = {int(k): v for k, v in _CATS["CAT-011"].items()}

# Subconjunto de unidades de medida permitidas para ítems (CAT-014)
UNIDADES_MEDIDA_PERMITIDAS = {59, 99}

PLAZO = _CATS["CAT-018"]

TIPO_DOC_REC = _CATS["CAT-022"].copy()
TIPO_DOC_REC.setdefault("00", "Sin documento")

CONDICION_OPERACION = {int(k): v for k, v in _CATS["CAT-016"].items()}

FORMA_PAGO = _CATS["CAT-017"]

TIPO_INVALIDACION = {int(k): v for k, v in _CATS["CAT-024"].items()}

# Catálogos geográficos
CAT_DEPTOS = _CATS["CAT-012"]

# Subconjunto representativo de municipios-44.
# Cada código está asociado a uno o más departamentos según CAT-013.
_CAT_MUNI44_COMPAT = [
    ("00", "00", "Otro (Para extranjeros)"),
    ("01", "13", "Ahuachapán Norte"),
    ("01", "14", "Ahuachapán Centro"),
    ("01", "15", "Ahuachapán Sur"),
    ("02", "14", "Santa Ana Norte"),
    ("02", "15", "Santa Ana Centro"),
    ("02", "16", "Santa Ana Este"),
    ("02", "17", "Santa Ana Oeste"),
    ("03", "17", "Sonsonate Norte"),
    ("03", "18", "Sonsonate Centro"),
    ("03", "19", "Sonsonate Este"),
    ("03", "20", "Sonsonate Oeste"),
    ("04", "34", "Chalatenango Norte"),
    ("04", "35", "Chalatenango Centro"),
    ("04", "36", "Chalatenango Sur"),
    ("05", "23", "La Libertad Norte"),
    ("05", "24", "La Libertad Centro"),
    ("05", "25", "La Libertad Oeste"),
    ("05", "26", "La Libertad Este"),
    ("05", "27", "La Libertad Costa"),
    ("05", "28", "La Libertad Sur"),
    ("06", "20", "San Salvador Norte"),
    ("06", "21", "San Salvador Oeste"),
    ("06", "22", "San Salvador Este"),
    ("06", "23", "San Salvador Centro"),
    ("06", "24", "San Salvador Sur"),
    ("07", "17", "Cuscatlán Norte"),
    ("07", "18", "Cuscatlán Sur"),
    ("08", "23", "La Paz Oeste"),
    ("08", "24", "La Paz Centro"),
    ("08", "25", "La Paz Este"),
    ("09", "10", "Cabañas Oeste"),
    ("09", "11", "Cabañas Este"),
    ("10", "14", "San Vicente Norte"),
    ("10", "15", "San Vicente Sur"),
    ("11", "24", "Usulután Norte"),
    ("11", "25", "Usulután Este"),
    ("11", "26", "Usulután Oeste"),
    ("12", "21", "San Miguel Norte"),
    ("12", "22", "San Miguel Centro"),
    ("12", "23", "San Miguel Oeste"),
    ("13", "27", "Morazán Norte"),
    ("13", "28", "Morazán Sur"),
    ("14", "19", "La Unión Norte"),
    ("14", "20", "La Unión Sur"),
]

CAT_MUNI44: dict[str, dict[str, str]] = {}
CAT_MUNI44_BY_DEPTO: dict[str, dict[str, str]] = {}
for dep_code, muni_code, name in _CAT_MUNI44_COMPAT:
    info = CAT_MUNI44.setdefault(muni_code, {})
    info[dep_code] = name
    by_dep = CAT_MUNI44_BY_DEPTO.setdefault(dep_code, {})
    by_dep[muni_code] = name


def _municipality_name_candidates(muni_code: str, dep_code: str | None) -> list[tuple[str, str]]:
    """Return ordered ``(dep, name)`` pairs for ``muni_code`` prioritising ``dep_code``."""

    candidates: list[tuple[str, str]] = []
    if dep_code is not None:
        dep_specific = CAT_MUNI44_BY_DEPTO.get(dep_code, {}).get(muni_code)
        if dep_specific:
            candidates.append((dep_code, dep_specific))

    info = CAT_MUNI44.get(muni_code)
    if not info:
        return candidates

    for dep, name in info.items():
        if dep_code is not None and dep == dep_code and candidates:
            # Already appended the department-specific name.
            continue
        candidates.append((dep, name))
    return candidates


class GeoValidationError(ValueError):
    """Raised when a department/municipality combination is invalid."""


def _normalize_tokens(value: str) -> list[str]:
    """Return a list of lower-case tokens without accents or punctuation."""

    normalized = unicodedata.normalize("NFD", value or "")
    normalized = "".join(
        ch for ch in normalized if unicodedata.category(ch) != "Mn"
    )
    normalized = re.sub(r"[^0-9a-z]+", " ", normalized.lower())
    return [token for token in normalized.split() if token]


def _contains_token_sequence(haystack: list[str], needle: list[str]) -> bool:
    """Check whether ``needle`` appears as a consecutive subsequence in ``haystack``."""

    if not needle or not haystack or len(needle) > len(haystack):
        return False
    window = len(needle)
    return any(haystack[i : i + window] == needle for i in range(len(haystack) - window + 1))


def validar_dep_muni_por_catalogo(
    dep: str | int | None, muni: str | int | None, strict: bool = True
) -> tuple[str, str]:
    """Validate ``departamento`` and ``municipio`` against CAT-012/013.

    Parameters
    ----------
    dep, muni:
        Códigos de departamento y municipio a validar.
    strict:
        Si ``True`` lanza :class:`GeoValidationError` cuando el municipio no
        pertenece al departamento.

    Returns
    -------
    tuple[str, str]
        Códigos normalizados de departamento y municipio.
    """

    def _fallback(reason: str) -> tuple[str, str]:
        warnings.warn(
            (
                f"{reason}; utilizando valores por defecto de dirección "
                "(06-San Salvador / 23-San Salvador Sur)"
            ),
            UserWarning,
        )
        return "06", "23"

    if dep is None:
        return _fallback("Departamento ausente")
    dep_raw = str(dep).strip()
    if not dep_raw.isdigit():
        return _fallback("Departamento inválido")
    dep_code = dep_raw.zfill(2)
    if dep_code not in CAT_DEPTOS:
        return _fallback("Departamento no existe en CAT-012")

    if muni is None:
        return _fallback("Municipio ausente")
    muni_raw = str(muni).strip()
    if not muni_raw.isdigit():
        return _fallback("Municipio inválido")
    muni_code = muni_raw.zfill(2)
    info = CAT_MUNI44.get(muni_code)
    if not info:
        return _fallback("Municipio-44 no existe en CAT-013")

    dep_name = CAT_DEPTOS[dep_code]
    dept_tokens = _normalize_tokens(dep_name)
    candidates = _municipality_name_candidates(muni_code, dep_code)
    matching_deps = [
        dep_candidate
        for dep_candidate, name in candidates
        if _contains_token_sequence(_normalize_tokens(name), dept_tokens)
    ]
    if dep_code in matching_deps or (matching_deps and dep_code not in info):
        return dep_code, muni_code

    if not strict:
        return dep_code, muni_code

    if dep_code in info:
        return dep_code, muni_code

    allowed = ", ".join(
        f"{dep} ({CAT_DEPTOS.get(dep, dep)}: {name})"
        for dep, name in sorted(info.items())
    )
    warnings.warn(
        (
            "Municipio {muni} no coincide por palabra con el departamento {dep} "
            "({dep_name}). Válido según catálogo para: {allowed}; utilizando "
            "valores por defecto de dirección (06-San Salvador / 23-San Salvador Sur)"
        ).format(
            muni=muni_code, dep=dep_code, dep_name=dep_name, allowed=allowed
        ),
        UserWarning,
    )
    return "06", "23"

# Conjuntos derivados
# Códigos permitidos en el resumen según el esquema oficial del DTE
TRIBUTOS_PERMITIDOS_RESUMEN_SCHEMA = {
    TRIBUTO_IVA,
    "C3",
    "59",
    "71",
    "D1",
    "C8",
    "D5",
    "D4",
    "C5",
    "C6",
    "C7",
    "19",
}
TRIBUTOS_PERMITIDOS_RESUMEN = set(TRIBUTOS_PERMITIDOS_RESUMEN_SCHEMA)
TRIBUTOS_PERMITIDOS_ITEM = set(TRIBUTOS_POR_ITEM_ESPECIALES)

# Mapa general de catálogos para acceso dinámico
CATALOGS: Dict[str, Dict[str, str]] = {key: val for key, val in _CATS.items()}
CATALOGS["TRIBUTOS"] = TRIBUTOS
CATALOGS["TIPO_ITEM"] = {str(k): v for k, v in TIPO_ITEM.items()}


# ---------------------------------------------------------------------------
# Esquemas JSON oficiales
# ---------------------------------------------------------------------------

ROOT_DIR = resource_path()
SCHEMAS_DIR = resource_path("svfe-json-schemas")
SCHEMA_MAP = {
    "01": str(resource_path("svfe-json-schemas", "fe-fc-v1.json")),
    "03": str(resource_path("svfe-json-schemas", "fe-ccf-v3.json")),
    "04": str(resource_path("svfe-json-schemas", "fe-nr-v3.json")),
    "05": str(resource_path("svfe-json-schemas", "fe-nc-v3.json")),
    "06": str(resource_path("svfe-json-schemas", "fe-nd-v3.json")),
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
        if code in TRIBUTOS_PERMITIDOS_RESUMEN_SCHEMA:
            TRIBUTOS_PERMITIDOS_RESUMEN.add(code)
        if code in TRIBUTOS_POR_ITEM_ESPECIALES:
            TRIBUTOS_PERMITIDOS_ITEM.add(code)
    elif cat == "TIPO_ITEM":
        try:
            TIPO_ITEM[int(code)] = label
        except ValueError:
            pass

