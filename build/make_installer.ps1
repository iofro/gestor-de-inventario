[CmdletBinding()]
param(
    [ValidateSet('full', 'update')]
    [string]$Mode = 'full',
    [string]$AppVersion,
    [string]$PythonPath = 'python',
    [string]$ISCCPath = 'ISCC.exe',
    [switch]$NoDefines
)

$ErrorActionPreference = 'Stop'

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = (Resolve-Path (Join-Path $scriptRoot '..')).Path
Set-Location $repoRoot

function Resolve-Tool {
    param(
        [Parameter(Mandatory = $true)][string]$Command,
        [Parameter(Mandatory = $true)][string]$FriendlyName
    )

    try {
        $cmd = Get-Command $Command -ErrorAction Stop
    } catch {
        throw "No se encontró $FriendlyName ('$Command'). Proporcione la ruta correcta."
    }

    return (Resolve-Path -LiteralPath $cmd.Path).Path
}

if (-not $AppVersion -or [string]::IsNullOrWhiteSpace($AppVersion)) {
    $versionFile = Join-Path $repoRoot 'VERSION'
    if (Test-Path -LiteralPath $versionFile) {
        $versionText = (Get-Content -LiteralPath $versionFile -ErrorAction SilentlyContinue | Select-Object -First 1).Trim()
        if ($versionText) {
            $AppVersion = $versionText
        }
    }
    if (-not $AppVersion) {
        $AppVersion = '0.0.0'
    }
}

$pythonExe = Resolve-Tool -Command $PythonPath -FriendlyName 'Python'
$isccExe = Resolve-Tool -Command $ISCCPath -FriendlyName 'Inno Setup (ISCC.exe)'

Write-Host "Versión del instalador: $AppVersion"
Write-Host "Python: $pythonExe"
Write-Host "Inno Setup: $isccExe"

$distDir = Join-Path $repoRoot 'dist/InventarioFarmacia'
if (Test-Path -LiteralPath $distDir) {
    Write-Host 'Eliminando build previo de PyInstaller...'
    Remove-Item -LiteralPath $distDir -Recurse -Force
}

Write-Host 'Ejecutando PyInstaller (modo --onedir)...'
$pyinstallerArgs = @('setup.py', '--mode', $Mode, '--bundle', 'onedir')
& $pythonExe @pyinstallerArgs
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller finalizó con código $LASTEXITCODE."
}

if (-not (Test-Path -LiteralPath $distDir -PathType Container)) {
    throw "No se generó el directorio '$distDir'."
}

$exePath = Join-Path $distDir 'InventarioFarmacia.exe'
if (-not (Test-Path -LiteralPath $exePath -PathType Leaf)) {
    throw "No se encontró el ejecutable generado: $exePath"
}

$signerDir = Join-Path $distDir 'svfe-api-firmador'
if (-not (Test-Path -LiteralPath $signerDir -PathType Container)) {
    throw "No se encontró la carpeta del firmador junto al ejecutable: $signerDir"
}

$uploadsDir = Join-Path $signerDir 'uploads'
if (Test-Path -LiteralPath $uploadsDir) {
    Write-Host 'La carpeta uploads se excluirá automáticamente por Inno Setup.'
}

$primaryOutputDir = Join-Path $repoRoot 'installer/build/installer'
$defaultOutputDir = Join-Path $repoRoot 'build/installer'
if ($NoDefines) {
    if (-not (Test-Path -LiteralPath $defaultOutputDir)) {
        New-Item -ItemType Directory -Path $defaultOutputDir -Force | Out-Null
    }
} else {
    if (-not (Test-Path -LiteralPath $primaryOutputDir)) {
        New-Item -ItemType Directory -Path $primaryOutputDir -Force | Out-Null
    }
}

$issPath = Join-Path $repoRoot 'installer/vertexdte.iss'
if (-not (Test-Path -LiteralPath $issPath -PathType Leaf)) {
    throw "No se encontró el script de Inno Setup: $issPath"
}

$innoArgs = @($issPath)
if (-not $NoDefines) {
    $innoArgs += "/DAppVersion=$AppVersion"
    $innoArgs += '/DBuildOutputDir="installer\build\installer"'
}

Write-Host 'Compilando instalador con Inno Setup...'
$innoOutput = & $isccExe @innoArgs 2>&1
$exitCode = $LASTEXITCODE
if ($innoOutput) {
    $innoOutput | ForEach-Object { Write-Host $_ }
}

if ($exitCode -ne 0) {
    Write-Error "ISCC.exe finalizó con código $exitCode."
    exit $exitCode
}

if ($NoDefines) {
    $effectiveOutputDir = $defaultOutputDir
    $effectiveVersion = '0.0.0'
} else {
    $effectiveOutputDir = $primaryOutputDir
    $effectiveVersion = $AppVersion
}

$expectedInstaller = Join-Path $effectiveOutputDir "VertexDTE-Setup-$effectiveVersion.exe"
if (Test-Path -LiteralPath $expectedInstaller -PathType Leaf) {
    Write-Host "Instalador generado: $expectedInstaller"
} else {
    Write-Warning "No se encontró el instalador esperado en '$expectedInstaller'."
}

exit 0
