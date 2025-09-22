# Compilación y empaquetado de Vertex DTE

Este documento explica cómo generar, con un único comando, tanto el directorio
"onedir" de PyInstaller como el instalador de Windows usando Inno Setup.

## Requisitos previos

* Windows 10 u 11.
* [Python 3.11](https://www.python.org/downloads/windows/) instalado y agregado al `PATH`.
* [Inno Setup 6](https://jrsoftware.org/isinfo.php) disponible en el `PATH` (opcional, sólo si se desea generar el instalador).
* Permisos para ejecutar scripts de PowerShell (`Set-ExecutionPolicy -Scope Process RemoteSigned`).

## Flujo interactivo

1. Abre PowerShell en la raíz del repositorio.
2. Ejecuta el script todo-en-uno:

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\build\release_interactivo.ps1
   ```

3. Selecciona la carpeta de salida, la carpeta raíz del firmador y confirma (o
   ajusta) la versión que se utilizará en los artefactos.

El proceso crea:

* `dist/VertexDTE/`: carpeta lista para ejecutar `VertexDTE.exe` en modo *onedir*.
* `<OutputDir>\VertexDTE-<versión>-win64.zip`: copia comprimida de la carpeta anterior.
* `<OutputDir>\VertexDTE-Setup-<versión>.exe`: instalador generado con Inno Setup (si `ISCC.exe` está disponible).

Dentro de la carpeta `extras\firmador\` del bundle se copia íntegramente la
estructura del firmador suministrado.

El firmador seleccionado se copia dentro del paquete en `extras\firmador\` y el
instalador genera `%APPDATA%\VertexDTE\settings.json` con la ruta instalada del
firmador (`{app}\extras\firmador\...`).

## Flujo no interactivo

Para automatizar el proceso (por ejemplo en CI) ejecuta:

```powershell
powershell -ExecutionPolicy Bypass -File .\build\release_interactivo.ps1 `
  -NoUI -OutputDir "D:\Releases" -SignerDir "D:\svfe-api-firmador" -Version 1.4.2
```

Los parámetros `-OutputDir` y `-SignerDir` son obligatorios cuando se usa `-NoUI`.
Si omites `-Version`, se tomará el valor del archivo `VERSION` (o `1.0.0` por
omisión).

Al finalizar se generan los mismos artefactos que en el modo interactivo y se
valida automáticamente que `dist/VertexDTE/extras/firmador/` contenga la copia
completa del firmador proporcionado.

## Dónde quedan los datos de la aplicación

Vertex DTE guarda su configuración, registros y documentos generados en
`%APPDATA%\VertexDTE\`, evitando escribir en `{app}` durante la ejecución.
Durante la instalación se crea (o actualiza) `settings.json` apuntando al
firmador instalado en `{app}\extras\firmador\`.

## Pruebas manuales recomendadas

1. Ejecuta `VertexDTE-Setup-<versión>.exe` e instala en la ubicación predeterminada.
2. Comprueba que la aplicación se inicia desde el menú Inicio y que los recursos
   (iconos, plantillas, estilos) se cargan correctamente.
3. Genera un PDF de prueba y verifica que se guarda en la carpeta de usuario
   (`%APPDATA%\VertexDTE`).
4. Comprueba que el firmador quedó instalado en
   `C:\Program Files\Vertex DTE\extras\firmador\` con todos sus archivos.
