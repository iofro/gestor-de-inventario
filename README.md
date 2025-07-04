# Gestor de Inventario

Esta aplicación permite gestionar inventarios y ventas utilizando una interfaz basada en **PyQt5**.

## Instalación

1. Asegúrate de tener Python 3.9 o superior.
2. Instala las dependencias ejecutando:

```bash
pip install -r requirements.txt
```

Esto instalará también **PyMuPDF**, utilizado para generar las previsualizaciones de las facturas en PDF.

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

### Datos del negocio y correo

La configuración general se almacena en `datos_negocio.json`. Para que el envío
de facturas por correo funcione, completa los campos SMTP de este archivo. La
contraseña de la cuenta utilizada para enviar correos ya **no** se guarda en el
archivo. En su lugar, define la variable de entorno `INVENTARIO_EMAIL_PASSWORD`
con la contraseña correspondiente antes de ejecutar la aplicación.

