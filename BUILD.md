# Compilación y empaquetado de Vertex DTE

Este documento describe cómo construir el ejecutable de Vertex DTE con PyInstaller
(
modo *onedir*) y cómo generar el instalador de Windows con Inno Setup. Los pasos
fueron probados en Windows 11 con PowerShell.

## Requisitos previos

* Windows 10 u 11.
* [Python 3.11](https://www.python.org/downloads/windows/) instalado y agregado al `PATH`.
* [Inno Setup 6](https://jrsoftware.org/isinfo.php) (para generar el instalador).
* Permisos para ejecutar scripts de PowerShell (`Set-ExecutionPolicy -Scope Process RemoteSigned`).

## Construir el ejecutable con PyInstaller

1. Clona el repositorio y abre una sesión de PowerShell en la raíz del proyecto.
2. Ejecuta el script de build:

   ```powershell
   ./build/build.ps1
   ```

   El script crea un entorno virtual, instala las dependencias y ejecuta
   PyInstaller con la especificación `build/VertexDTE.spec`. Al finalizar se
   valida que `dist/VertexDTE/VertexDTE.exe` se inicie correctamente.

   El icono de la aplicación se reconstruye automáticamente desde un blob
   codificado en Base64 dentro de la especificación, evitando versionar
   binarios.

3. El ejecutable se encuentra en `dist/VertexDTE/`. Copia el directorio completo
   para distribuirlo manualmente o continuar con el instalador.

> **Nota:** PyInstaller se ejecuta en modo *onedir* para reducir falsos positivos
de antivirus y permitir inspeccionar fácilmente los archivos generados.

## Generar el instalador con Inno Setup

1. Asegúrate de haber ejecutado previamente PyInstaller; `dist/VertexDTE/` debe
   contener los binarios actualizados.
2. Abre "Inno Setup Compiler" y carga `build/VertexDTE.iss`.
3. Compila el script (`F9`). El archivo resultante `VertexDTE-Setup.exe` se
   guarda en el directorio `build/Output/` por defecto.

La versión utilizada por Inno Setup se lee automáticamente desde el archivo
`VERSION` del proyecto, por lo que no es necesario editar el script manualmente.

### Compilación silenciosa

Si prefieres una compilación automatizada, puedes ejecutar en PowerShell (desde
la raíz del repositorio):

```powershell
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" /Qp build/VertexDTE.iss
```

Ajusta la ruta de `ISCC.exe` si instalaste Inno Setup en otra ubicación.

## Pruebas manuales recomendadas (VM "limpia")

1. Ejecuta `VertexDTE-Setup.exe` e instala en la ubicación predeterminada.
2. Abre la aplicación desde el menú Inicio y confirma que la interfaz carga los
   recursos (iconos, plantillas, estilos).
3. Genera un PDF de prueba desde la pestaña correspondiente.
4. Envía un DTE en ambiente de pruebas (puedes simular o reutilizar un token).
5. Verifica que los archivos de configuración y los registros se creen en
   `%APPDATA%\VertexDTE`.
6. Comprueba que el selector de DTE lista resultados (si la base de datos está
   disponible en esa máquina).
7. Valida la previsualización o impresión utilizando QtPrintSupport.

## Integración continua

El repositorio incluye el flujo de trabajo `.github/workflows/windows-build.yml`
que ejecuta PyInstaller en `windows-latest`, sube el artefacto resultante y puede
servir como base para acciones de publicación.

## Consideraciones de seguridad

* Windows SmartScreen y algunos antivirus pueden marcar binarios nuevos como
  desconocidos. Distribuir el directorio completo (*onedir*) facilita la
  inspección y reduce falsos positivos.
* Usa certificados de firma de código si cuentas con ellos para reducir alertas
  durante la instalación.
