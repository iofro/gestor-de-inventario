# Gestor de Inventario

Esta aplicación permite gestionar inventarios y ventas utilizando una interfaz basada en **PyQt5**.

## Instalación

1. Asegúrate de tener Python 3.9 o superior.
2. Instala las dependencias ejecutando:

```bash
pip install -r requirements.txt
```

Esto instalará también **PyMuPDF** para las previsualizaciones de facturas.

## Ejecutar la aplicación

Ejecuta el archivo `main.py` para iniciar la interfaz gráfica:

```bash
python main.py
```

La ventana principal mostrará el icono incluido en `logoinventario.jpg`. Puedes
reemplazar este archivo con tu propia imagen para personalizar el logo de la
aplicación.

Se cargará el último inventario si está disponible y podrás comenzar a registrar compras y ventas.

## Empaquetado con PyInstaller

Puedes generar un ejecutable independiente con **PyInstaller** usando:

```bash
pyinstaller --onefile --windowed \
    --add-data "style.qss;." --add-data "logoinventario.jpg;." \
    --add-data "inventario.db;." main.py
```

El comando anterior también está preconfigurado en `setup.py`, por lo que puedes ejecutar `python setup.py` si prefieres.

Si la interfaz no aparece al ejecutar el binario, inicia el programa desde una terminal para ver los mensajes de error.

## Pruebas

Las pruebas unitarias se ejecutan con **pytest**. Para lanzarlas usa:

```bash
pytest
```

Las pruebas que verifican la generación y lectura de PDF utilizan
**PyMuPDF**, por lo que debes instalar las dependencias antes de
ejecutarlas. Puedes hacerlo ejecutando:

```bash
pip install -r requirements.txt
```

Para una prueba manual de extremo a extremo contra el entorno de
Hacienda, ejecuta:

```bash
python -m tests.manual_e2e
```

### Generar DTE

El método `generar_dte_json(venta_id)` crea un diccionario con el formato que
Hacienda requiere para un DTE. Este resultado puede enviarse a la plataforma
de facturación electrónica o almacenarse junto a la venta.

```python
from db import DB

db = DB()
dte = db.generar_dte_json(venta_id=1)
```

Para transmitir los DTE hacia la API de Hacienda añade en `datos_negocio.json` un
bloque de configuración similar al siguiente:

```json
{
  "dte_api": {
    "url": "https://api.hacienda.test/fesv/recepciondte",
    "ambiente": "produccion" | "pruebas",
    "token": "TOKEN_O_CREDENCIAL"
  }
}
```
`dte_api.url` es la **fuente primaria** de la URL de recepción. La ruta
`/fesv/recepciondte` se añadirá automáticamente si solo se indica el host. El
archivo `config_negocio.json` puede proveer valores de respaldo
(`recepcion_url`, `url` o `endpoint`), pero siempre serán **sobrescritos** por lo
configurado en `datos_negocio.json`.

La función `transmitir_dte(db, venta_id)` utilizará la URL resultante para
enviar el DTE inmediatamente después de firmarlo en modo normal, o registrará
un evento pendiente en modo de contingencia.

Cuando se use el modo de contingencia con `tipoContingencia` igual a `5`, el
campo `motivo_contin` permite describir la causa de la contingencia con una
longitud de entre 5 y 500 caracteres.

### Condición de operación

El campo `resumen.condicionOperacion` se normaliza siguiendo el catálogo
oficial **CAT‑016**: `1` = Contado, `2` = Crédito y `3` = Otro. Es posible
proporcionar el código numérico o un alias textual (por ejemplo,
"contado" o "crédito"), que se convertirán automáticamente al valor
correspondiente. Cuando se indique **Crédito**, cada entrada en `pagos`
debe incluir los campos `plazo` y `periodo`.

### Datos del negocio y correo

La configuración general se almacena en `datos_negocio.json`. Para que el envío
de facturas por correo funcione, completa los campos SMTP de este archivo. Puedes
especificar la contraseña directamente en `email_contrasena` o definir la
variable de entorno `INVENTARIO_EMAIL_PASSWORD` antes de ejecutar la aplicación;
la variable de entorno tiene prioridad si se define.

El campo `cod_giro` identifica el giro del negocio y se usa al generar el DTE
como `emisor.codActividad`.

Si estás ejecutando pruebas automatizadas o no planeas enviar correos, puedes
evitar la advertencia sobre credenciales incompletas estableciendo la variable
de entorno `INVENTARIO_SUPPRESS_SMTP_WARNING=1` o iniciando `SalesTab` con
`check_smtp=False`.

Para firmar electrónicamente los DTE define en `config_negocio.json` la
configuración por ambiente. El campo `ambiente` indica qué sección utilizar
(`pruebas` o `produccion`) y dentro de cada una se debe agregar su propio bloque
`firma_electronica` con las credenciales del firmador:

```json
{
  "sign_url": "http://127.0.0.1:8080/firma/firmardocumento/",
  "ambiente": "pruebas",
  "pruebas": {
    "firma_electronica": {
      "nit": "09061712791014",
      "passwordPri": "PASSWORD_EN_BASE64",
      "activo": true
    }
  },
  "produccion": {
    "firma_electronica": {
      "nit": "NIT_PRODUCCION",
      "passwordPri": "PASSWORD_PROD_EN_BASE64",
      "activo": true
    }
  }
}
```

El campo `passwordPri` puede almacenarse codificado en Base64 y será
decodificado automáticamente al leer la configuración.

Los datos se guardan dentro del nodo del ambiente (`pruebas` o `produccion`),
por lo que cada uno debe contar con su propio bloque `firma_electronica`.

Coloca el certificado correspondiente en `svfe-api-firmador/uploads/<NIT>.crt`. La carpeta
`uploads/` está incluida en `.gitignore`, por lo que los certificados no se versionan en el
repositorio. Si deseas utilizar otra ubicación, define la variable de entorno
`CERT_UPLOAD_DIR`; tanto la aplicación como el servicio de firmado la utilizan (los espacios
ocultos se eliminan al leerla). Cuando se carga un certificado desde la interfaz de
configuración, la carpeta `uploads/` se vacía antes de copiar el nuevo archivo, asegurando
que solo el certificado vigente permanezca en ese directorio.

El servicio de firmado debe ejecutarse con:

```bash
vendor/jdk/bin/java -jar target/svfe-api-firmador-0.1.1.jar --server.port=8080
```

El puerto por defecto es `8080`, pero puede cambiarse editando el archivo
`application.yml` del servicio:

```yaml
server:
  port: 8080
```

Si el firmador escucha en otro puerto o en otro equipo, especifica la URL
mediante la variable de entorno `SIGN_URL`:

```bash
export SIGN_URL="http://127.0.0.1:8080/firma/firmardocumento/"
```

Alternativamente, puede definirse en `config_negocio.json` bajo la clave
`sign_url`.

Luego se firmará cada DTE enviándolo a
`http://127.0.0.1:8080/firma/firmardocumento/` de forma automática si no se
especifica otra URL.

### Firmar un DTE manualmente

Desde el menú **Configuración** de la aplicación puedes escoger la opción
"**Firmar DTE...**" para seleccionar un archivo `.json` previamente
generado y enviarlo al servicio local de firmado. El resultado se guarda
como archivo `.jws` en la ubicación que elijas sin modificar el JSON
original.

El firmador utiliza HTTP por defecto. Si deseas habilitar HTTPS, define las
variables `SVFE_ARCHIVO` y `SVFE_PASSWORD` en un archivo `.env` (consulta
`.env.example`). Esta configuración es opcional y el perfil principal seguirá
siendo el modo normal basado en HTTP.

Para diferenciar entre los ambientes de pruebas y producción de Hacienda,
configura el campo `ambiente` y las URLs en `config_negocio.json`:

```json
{
  "ambiente": "pruebas",
  "pruebas": {
    "auth_url": "https://apitest.dtes.mh.gob.sv/seguridad/auth",
    "recepcion_url": "https://apitest.dtes.mh.gob.sv/fesv/recepciondte",
    "api_user": "MI_USUARIO_API",
    "api_pwd": "MI_CONTRASEÑA_API"
  },
  "produccion": {
    "auth_url": "https://api.factura.gob.sv/auth",
    "recepcion_url": "https://api.dtes.mh.gob.sv/fesv/recepciondte"
  }
}
```
Los valores de `recepcion_url` actúan como respaldo y serán reemplazados si se
define `dte_api.url` en `datos_negocio.json`. La aplicación buscará `auth_url`
y `recepcion_url` dentro del bloque del ambiente seleccionado (`pruebas` o
`produccion`). Al cambiar `ambiente` a `produccion` la aplicación utilizará los
servicios productivos.

Dentro del mismo bloque puede definirse `api_user` y `api_pwd` para
especificar el usuario y la contraseña de la API. Estos datos se utilizan
al solicitar el token de autenticación. También es posible obtener un
token programáticamente llamando a `auth.get_token(nit="USUARIO", pwd="CLAVE")`.

El token obtenido se almacena en la base de datos `inventario.db` con
permisos restringidos al usuario que ejecuta la aplicación. Si se desea
eliminar voluntariamente el token guardado puede invocarse
`auth.delete_token()`.

La contraseña puede dejarse vacía si la clave privada no está cifrada. Al
generar facturas o tickets se creará junto al PDF un archivo `.jws` con el JSON
firmado.

La pestaña **Configuración de Facturación Electrónica** permite definir
otros parámetros dentro de `datos_negocio.json` bajo el bloque `dte_api`:

```json
{
  "dte_api": {
    "token": "TOKEN",
    "prefijo_control": "DTE-01-S001P001",
    "modo_transmision": "1 - Normal",
    "tipo_contingencia": 1,
    "motivo_contin": ""
  }
}
```

Cuando `modo_transmision` es "2 - Contingencia", debe definirse también
`tipo_contingencia` (valores del 1 al 5). Si se utiliza el valor `5` es
obligatorio proporcionar un `motivo_contin` con al menos cinco caracteres.

Las facturas generadas desde la pestaña **Ventas** se guardan automáticamente en
`facturas_consumidor_final` o `facturas_credito_fiscal` dependiendo del tipo de
documento. Los tickets se almacenan en la carpeta `tickets`. Al imprimir,
previsualizar o enviar por correo se reutilizan estos PDFs si están disponibles.
Las notas de débito creadas desde la pestaña **Facturación** se guardan en la
carpeta `notas_debito`. Las notas de crédito generadas desde la misma pestaña se
almacenan en la carpeta `notas_credito`, junto con su archivo JSON.
Además, la pestaña **Facturación** buscará archivos también en las rutas
`facturas/consumidor_final` y `facturas/credito_fiscal` si existen, de modo que
las facturas almacenadas manualmente en esas carpetas se muestren incluso si no
están vinculadas a una venta.

Cuando alguna herramienta requiera la ruta de un `dte.json`, apunta al archivo
JSON ubicado en estas mismas carpetas. En Windows la ruta luce similar a:
`C:\Users\usuario\Desktop\repositorio de github\facturas_consumidor_final\20250817_ariel_15_ConsumidorFinal.json`.

### Firmado y pruebas

Para iniciar el servicio de firmado:

```bash
java -jar svfe-api-firmador-*.jar --server.port=8080
```

En PowerShell puedes definir las variables necesarias:

```powershell
setx SIGN_URL "http://127.0.0.1:8080/firma/firmardocumento/"
setx NIT_FIRMADOR "09061712791014"
setx HACIENDA_URL "https://apitest.ejemplo.hacienda.sv/..."
```

Coloca el certificado del NIT correspondiente en `svfe-api-firmador/uploads/<NIT>.crt`.
La aplicación limpiará esta carpeta antes de copiar un nuevo certificado desde la
interfaz. También puedes especificar otra ruta con la variable de entorno
`CERT_UPLOAD_DIR`.

Ejecuta las pruebas manuales con:

```bash
python -m tests.manual_sign_check
python -m tests.manual_e2e
```

Las salidas esperadas son `SIGN_TEST_OK` o `SIGN_TEST_FAIL` y `E2E_API_OK` o `E2E_API_FAIL` respectivamente.

### Generar ticket en formato personalizado

En las pestañas **Ventas** y **Facturación** hay un botón `Ticket`.
Al pulsarlo se genera automáticamente un archivo `ticket_{id}.pdf` dentro de la
carpeta `tickets`. El ticket utiliza un formato básico y lee los datos de
`datos_negocio.json`. Modifica ese archivo para personalizar nombre, dirección y
otros datos.

Si quieres mostrar tu logo, reemplaza `logoinventario.jpg` por tu imagen.

Como referencia puedes revisar `ticket_example.pdf` que se
incluye en este repositorio.

Para reproducir ese ejemplo ejecuta lo siguiente:

```python
import json
from ticket_pdf import generar_ticket_personalizado

with open("tests/data/sample_ticket.json", encoding="utf-8") as f:
    data = json.load(f)

generar_ticket_personalizado(
    data["venta"],
    data["detalles"],
    "mi_ticket.pdf",
    datos_negocio=data["datos_negocio"],
    dte_data=data["dte_data"],
)
```
