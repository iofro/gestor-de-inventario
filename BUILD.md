# Empaquetado de Vertex DTE

Este documento describe cómo generar el paquete portable (PyInstaller en modo
*onedir*) y el instalador de Windows (Inno Setup) utilizando el script
`build/release_interactivo.ps1`.

## Requisitos previos

- Windows 10 u 11.
- [Python 3.11](https://www.python.org/downloads/windows/) instalado y agregado al
  `PATH`.
- [Inno Setup 6](https://jrsoftware.org/isinfo.php) (opcional pero recomendado
  para crear el instalador).
- Permisos para ejecutar scripts de PowerShell (por ejemplo
  `Set-ExecutionPolicy -Scope Process RemoteSigned`).

## Ejecución interactiva

Desde la raíz del repositorio abre PowerShell y ejecuta:

```powershell
powershell -ExecutionPolicy Bypass -File .\build\release_interactivo.ps1
```

El asistente abrirá dos cuadros de diálogo para seleccionar la carpeta de
salida y el archivo del firmador, y permitirá introducir la versión (se propone
la del archivo `VERSION` si existe). Tras confirmar, el script crea un entorno
virtual, ejecuta PyInstaller con `build/VertexDTE.spec`, copia el firmador dentro
del paquete en `extras/firmador/` y comprime el resultado.

## Ejecución sin interfaz

Si prefieres automatizar todo, puedes ejecutar el mismo script con parámetros:

```powershell
powershell -ExecutionPolicy Bypass -File .\build\release_interactivo.ps1 `
  -NoUI -OutputDir "D:\Releases" `
  -Signer "D:\Firmador\FirmadorMH.exe" `
  -Version 1.4.2
```

En modo `-NoUI` los parámetros `-OutputDir` y `-Signer` son obligatorios. Si
`-Version` se omite, se usará el valor definido en `VERSION` o `1.0.0` por
omisión.

## Artefactos generados

Al finalizar el script tendrás:

- `dist/VertexDTE/VertexDTE.exe`: carpeta resultante de PyInstaller (modo
  *onedir*).
- `<OutputDir>\VertexDTE-<versión>-win64.zip`: paquete comprimido del directorio
  `dist/VertexDTE/`.
- `<OutputDir>\VertexDTE-Setup-<versión>.exe`: instalador generado por Inno Setup
  (solo si `ISCC.exe` está disponible).

El firmador seleccionado se copia al paquete en `extras\firmador\<archivo>` y
tras instalar quedará en
`C:\Program Files\Vertex DTE\extras\firmador\<archivo>`.

Si Inno Setup no está instalado, el script avisa y conserva únicamente la carpeta
`dist/VertexDTE/` y el ZIP.

## Notas y recomendaciones

- PyInstaller se ejecuta en modo *onedir* para reducir falsos positivos de
  antivirus y facilitar la inspección de los archivos generados.
- El `.spec` incluye los recursos (`assets`, `templates`, `facturas_*`,
  `notas_*`, `dtes`, `extras/firmador`, etc.) y los certificados TLS de
  `certifi`.
- La aplicación resuelve los recursos mediante `resource_path` y guarda
  configuración, logs y PDFs en `%APPDATA%\VertexDTE\`, evitando escribir en
  `Program Files` en tiempo de ejecución.
- Puedes reutilizar los artefactos en flujos de CI/CD ejecutando el script en un
  `windows-latest` con Python 3.11 e Inno Setup instalados.

## Pruebas manuales sugeridas

En una máquina limpia (sin Python):

1. Instala con `VertexDTE-Setup-<versión>.exe` y deja la ruta por defecto.
2. Abre la aplicación desde el menú Inicio y verifica que los recursos (iconos,
   plantillas, estilos) se cargan.
3. Genera un PDF de prueba y comprueba que aparece en
   `%APPDATA%\VertexDTE`.
4. Envía un DTE en ambiente de pruebas y revisa que los logs/configuraciones se
   escriben también en `%APPDATA%\VertexDTE`.
5. Utiliza la previsualización/impresión para confirmar que QtPrintSupport está
   incluido en el bundle.
