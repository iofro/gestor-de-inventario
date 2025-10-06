[CmdletBinding()]
param(
    [string]$AppVersion
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

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    throw 'Python no se encuentra en el PATH.'
}

Push-Location $repoRoot
try {
    $distDir = Join-Path $repoRoot 'dist'
    $buildDir = Join-Path $distDir 'InventarioFarmacia'
    if (Test-Path $buildDir) {
        Remove-Item -Recurse -Force $buildDir
    }

    & $python.Path 'setup.py' '--mode' 'full' '--bundle' 'onedir'

    if (-not (Test-Path (Join-Path $buildDir 'InventarioFarmacia.exe'))) {
        throw 'La compilación de PyInstaller no generó InventarioFarmacia.exe en modo --onedir.'
    }
}
finally {
    Pop-Location
}

$signerDir = Join-Path $repoRoot 'svfe-api-firmador'
if (-not (Test-Path $signerDir)) {
    throw 'No se encontró la carpeta svfe-api-firmador requerida.'
}

$uploadsDir = Join-Path $signerDir 'uploads'
if (Test-Path $uploadsDir) {
    Write-Host 'La carpeta uploads existente no será empaquetada (se preservarán certificados).'
} else {
    Write-Host 'Creando carpeta uploads vacía para asegurar la estructura esperada.'
    New-Item -ItemType Directory -Path $uploadsDir | Out-Null
}

$iscc = Get-Command ISCC.exe -ErrorAction SilentlyContinue
if (-not $iscc) {
    throw 'No se encontró ISCC.exe en el PATH. Instala Inno Setup o agrega su carpeta al PATH.'
}

$installerDir = Join-Path $repoRoot 'installer'
$issFile = Join-Path $installerDir 'vertexdte.iss'
if (-not (Test-Path $issFile)) {
    throw 'No se encontró el script de Inno Setup installer/vertexdte.iss.'
}

$arguments = @($issFile, "/DAppVersion=$AppVersion")
& $iscc.Path @arguments

$expectedOutput = Join-Path $repoRoot 'build' 'installer' 'VertexDTE-Setup.exe'
if (Test-Path $expectedOutput) {
    Write-Host "Instalador generado en: $expectedOutput"
} else {
    Write-Warning 'La compilación de Inno Setup finalizó sin crear VertexDTE-Setup.exe.'
}
