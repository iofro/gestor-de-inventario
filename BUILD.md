# Guía de empaquetado Vertex DTE

Esta guía describe cómo generar el ejecutable de Vertex DTE con PyInstaller y
cómo producir el instalador de Windows mediante Inno Setup.

## Requisitos

* Windows 10 u 11 (64 bits)
* [Python 3.11](https://www.python.org/downloads/windows/)
* PowerShell 5+ o PowerShell 7+
* [Inno Setup](https://jrsoftware.org/isdl.php) 6.2 o superior (para compilar el instalador)
* Conexión a internet para instalar dependencias

> ℹ️ El script de construcción crea un entorno virtual en `.venv` dentro del
> repositorio. Puedes eliminar esa carpeta cuando termines.

## Compilar el ejecutable con PyInstaller

1. Abre una consola de PowerShell en la raíz del repositorio.
2. Ejecuta el script de construcción:

   ```powershell
   pwsh build/build.ps1
   ```

   El script realiza las siguientes tareas:

   * Crea el entorno virtual `.venv`.
   * Instala las dependencias de la aplicación junto con PyInstaller.
   * Regenera `assets/app.ico` a partir de `assets/app.ico.b64` cuando sea necesario.
   * Ejecuta `pyinstaller build/VertexDTE.spec --noconfirm --clean`.
   * Verifica que `dist/VertexDTE/VertexDTE.exe` inicie correctamente.

3. El ejecutable se encuentra en `dist/VertexDTE/VertexDTE.exe`. Distribuye la
   carpeta completa `dist/VertexDTE/` (modo *onedir*) para minimizar falsos
   positivos de antivirus.

## Generar el instalador con Inno Setup

1. Asegúrate de haber ejecutado PyInstaller y de que `dist/VertexDTE/` contenga
   el ejecutable.
2. Abre Inno Setup Compiler y carga `build/VertexDTE.iss`, o compílalo por línea
   de comandos con:

   ```powershell
   ISCC build/VertexDTE.iss
   ```

3. El instalador `VertexDTE-Setup.exe` se genera en la carpeta `build/` por
   defecto.

### Checklist de validación en una VM limpia

* Ejecutar `VertexDTE-Setup.exe` y completar la instalación.
* Confirmar que la aplicación se instala en `C:\Program Files\Vertex DTE\`.
* Abrir Vertex DTE desde el menú inicio y validar que la UI carga sin errores.
* Generar un PDF de prueba (por ejemplo, desde el módulo de facturación).
* Enviar un DTE en ambiente de pruebas (simula o configura un token válido).
* Verificar que `datos_negocio.json`, `config_negocio.json`, `logs` y cualquier
  PDF generado se almacenan en `%APPDATA%\VertexDTE\`.
* Probar que el selector de DTE muestra resultados con una base de datos real.
* Probar la vista previa/impresión para confirmar que `QtPrintSupport` está
  disponible.

## Integración continua

El flujo de trabajo `.github/workflows/windows-build.yml` compila la aplicación
en `windows-latest` con Python 3.11 y publica `dist/VertexDTE/` como artefacto.
Puedes descargar el artefacto desde la pestaña *Actions* de GitHub para obtener
el paquete generado automáticamente.

Para automatizar la creación del instalador agrega un paso que ejecute
`ISCC build/VertexDTE.iss` después de PyInstaller (requiere que Inno Setup esté
instalado en el *runner*).

## Notas adicionales

* La aplicación se ejecuta en modo *onedir* para reducir falsos positivos de
  antivirus.
* Los datos de usuario se guardan en `%APPDATA%\VertexDTE\` y nunca deben
  escribirse en `Program Files`.
* SmartScreen puede marcar el instalador como desconocido. Recomienda al usuario
  mantener el instalador firmado digitalmente si es posible, o confirmar el
  origen antes de continuar.
