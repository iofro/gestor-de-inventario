[CmdletBinding()]
param(
    [ValidateSet('full', 'update')]
    [string]$Mode = 'full',
    [string]$AppVersion,
    [string]$PythonPath,
    [string]$ISCCPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptRoot '..')

if (-not $AppVersion) {
    $versionFile = Join-Path $repoRoot 'VERSION'
    if (Test-Path $versionFile) {
        $AppVersion = (Get-Content $versionFile -TotalCount 1).Trim()
    }
    if (-not $AppVersion) {
        $AppVersion = '0.0.0'
    }
}

if ($PythonPath) {
    if (-not (Test-Path $PythonPath)) {
        throw "No se encontró Python en la ruta proporcionada: $PythonPath"
    }
    $pythonExecutable = (Resolve-Path $PythonPath).Path
} else {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pythonCommand) {
        throw 'Python no se encuentra en el PATH. Usa el parámetro -PythonPath para especificar la ruta al ejecutable.'
    }
    $pythonExecutable = $pythonCommand.Path
}

if ($ISCCPath) {
    if (-not (Test-Path $ISCCPath)) {
        throw "No se encontró ISCC.exe en la ruta proporcionada: $ISCCPath"
    }
    $isccExecutable = (Resolve-Path $ISCCPath).Path
} else {
    $isccCommand = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if (-not $isccCommand) {
        throw 'No se encontró ISCC.exe en el PATH. Instala Inno Setup o proporciona la ruta con -ISCCPath.'
    }
    $isccExecutable = $isccCommand.Path
}

$distDir = Join-Path $repoRoot 'dist'
$buildDir = Join-Path $distDir 'InventarioFarmacia'
$expectedExe = Join-Path $buildDir 'InventarioFarmacia.exe'

Push-Location $repoRoot
try {
    if (Test-Path $buildDir) {
        Remove-Item -Recurse -Force $buildDir
    }

    & $pythonExecutable 'setup.py' '--mode' $Mode '--bundle' 'onedir'

    if (-not (Test-Path $expectedExe)) {
        throw 'La compilación de PyInstaller no generó dist/InventarioFarmacia/InventarioFarmacia.exe.'
    }
}
finally {
    Pop-Location
}

$signerDir = Join-Path $repoRoot 'svfe-api-firmador'
if (-not (Test-Path $signerDir)) {
    throw 'No se encontró la carpeta svfe-api-firmador requerida para el instalador.'
}

$uploadsDir = Join-Path $signerDir 'uploads'
if (Test-Path $uploadsDir) {
    Write-Host 'La carpeta svfe-api-firmador\uploads se preservará fuera del instalador.'
} else {
    Write-Warning 'No se encontró la carpeta svfe-api-firmador\uploads; Inno Setup la creará vacía durante la instalación.'
}

$installerDir = Join-Path $repoRoot 'installer'
$issFile = Join-Path $installerDir 'vertexdte.iss'
if (-not (Test-Path $issFile)) {
    throw 'No se encontró el script de Inno Setup installer/vertexdte.iss.'
}

& $isccExecutable $issFile "/DAppVersion=$AppVersion"

$outputDir = Join-Path $installerDir 'build'
$outputDir = Join-Path $outputDir 'installer'
$outputExe = Join-Path $outputDir 'VertexDTE-Setup.exe'

if (Test-Path $outputExe) {
    Write-Host "Instalador generado en: $outputExe"
} else {
    throw 'Inno Setup finalizó sin crear installer/build/installer/VertexDTE-Setup.exe.'
}
