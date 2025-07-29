# Gestor de Inventario

Esta aplicación permite gestionar inventarios y ventas utilizando una interfaz basada en **PyQt5**.

## Instalación

1. Asegúrate de tener Python 3.9 o superior.
2. Instala las dependencias ejecutando:

```bash
pip install -r requirements.txt
```

Esto instalará también **PyMuPDF** para las previsualizaciones de facturas,
así como **PyJWT** y **cryptography**, necesarias para firmar los DTE.

## Ejecutar la aplicación

Ejecuta el archivo `main.py` para iniciar la interfaz gráfica:

```bash
python main.py
```

La ventana principal mostrará el icono incluido en `logoinventario.jpg`. Puedes
reemplazar este archivo con tu propia imagen para personalizar el logo de la
aplicación.

Se cargará el último inventario si está disponible y podrás comenzar a registrar compras y ventas.

## Pruebas

Las pruebas unitarias se ejecutan con **pytest**. Para lanzarlas usa:

```bash
pytest
```

Las pruebas que verifican la generación y lectura de PDF utilizan
**PyMuPDF**, por lo que debes instalar las dependencias (incluyendo
**PyJWT** y **cryptography**) antes de
ejecutarlas. Puedes hacerlo ejecutando:

```bash
pip install -r requirements.txt
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
    "url": "https://api.hacienda.test/dtes",
    "ambiente": "produccion" | "pruebas",
    "token": "TOKEN_O_CREDENCIAL"
  }
}
```
La función `transmitir_dte(db, venta_id)` utilizará estos datos para enviar el
DTE inmediatamente después de firmarlo en modo normal, o registrará un evento
pendiente en modo de contingencia.

### Datos del negocio y correo

La configuración general se almacena en `datos_negocio.json`. Para que el envío
de facturas por correo funcione, completa los campos SMTP de este archivo. La
contraseña de la cuenta utilizada para enviar correos ya **no** se guarda en el
archivo. En su lugar, define la variable de entorno `INVENTARIO_EMAIL_PASSWORD`
con la contraseña correspondiente antes de ejecutar la aplicación.

Para firmar electrónicamente los DTE define los archivos de firma en
`config_negocio.json` dentro del bloque `firma_electronica`:

```json
{
  "firma_electronica": {
    "certificado": "ruta/al/certificado.crt",
    "certificado_data": "PEM_O_BASE64",
    "clave_privada": "ruta/al/clave.key",
    "clave_privada_data": "PEM_O_BASE64",
    "llave_publica": "ruta/opcional/public.key",
    "llave_publica_data": "PEM_O_BASE64",
    "frase_acceso": "PASSWORD_EN_BASE64"
  }
}
```

La contraseña puede dejarse vacía si la clave privada no está cifrada. Al
generar facturas o tickets se creará junto al PDF un archivo `.jws` con el JSON
firmado.

La pestaña **Configuración de Facturación Electrónica** permite definir
otros parámetros dentro de `datos_negocio.json` bajo el bloque `dte_api`:

```json
{
  "dte_api": {
    "url": "https://api.hacienda.test/dtes",
    "ambiente": "pruebas",
    "token": "TOKEN",
    "prefijo_control": "DTE-01-S001P001",
    "modo_transmision": "1 - Normal"
  }
}
```

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
