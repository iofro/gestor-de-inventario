[CmdletBinding()]
param(
    [ValidateSet('full', 'update')]
    [string]$Mode = 'full',
    [string]$AppVersion,
    [string]$PythonPath,
    [string]$ISCCPath,
    [string]$OutputDir
)

$ErrorActionPreference = 'Stop'

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = (Resolve-Path (Join-Path $scriptRoot '..')).Path
Set-Location $repoRoot

function Get-AppVersion {
    param([string]$Requested)

    if ($Requested -and -not [string]::IsNullOrWhiteSpace($Requested)) {
        return $Requested.Trim()
    }

    $versionFile = Join-Path $repoRoot 'VERSION'
    if (Test-Path -LiteralPath $versionFile) {
        foreach ($line in Get-Content -Path $versionFile -ErrorAction SilentlyContinue) {
            $trimmed = $line.Trim()
            if (-not $trimmed) { continue }
            if ($trimmed -like 'version=*') { return $trimmed.Split('=')[-1].Trim() }
            if ($trimmed -notlike '#*') { return $trimmed }
        }
    }

    return '1.0.0'
}

function Resolve-Python {
    param([string]$Explicit)

    if ($Explicit) {
        $resolved = (Resolve-Path -LiteralPath $Explicit -ErrorAction Stop).Path
        return $resolved
    }

    $candidates = @('python.exe', 'python', 'py')
    foreach ($candidate in $candidates) {
        $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
        if (-not $cmd) { continue }
        if ($candidate -eq 'py') {
            try {
                $output = & $cmd.Path -3.11 -c "import sys;print(sys.executable)"
                if ($LASTEXITCODE -eq 0 -and $output) {
                    $exe = $output.Trim().Split("`n")[-1].Trim()
                    if ($exe -and (Test-Path -LiteralPath $exe)) {
                        return $exe
                    }
                }
            } catch { }
        }
        return $cmd.Path
    }

    throw 'No se encontró un intérprete de Python. Proporcione -PythonPath o agregue Python al PATH.'
}

function Resolve-ISCC {
    param([string]$Explicit)

    if ($Explicit) {
        return (Resolve-Path -LiteralPath $Explicit -ErrorAction Stop).Path
    }

    $cmd = Get-Command 'ISCC.exe' -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Path }

    $defaultPaths = @(
        'C:\\Program Files\\Inno Setup 6\\ISCC.exe',
        'C:\\Program Files (x86)\\Inno Setup 6\\ISCC.exe'
    )

    foreach ($path in $defaultPaths) {
        if (Test-Path -LiteralPath $path) {
            return $path
        }
    }

    throw 'No se encontró ISCC.exe. Proporcione -ISCCPath o instale Inno Setup 6.'
}

function Copy-SignerToExtras {
    $source = Join-Path $repoRoot 'svfe-api-firmador'
    if (-not (Test-Path -LiteralPath $source -PathType Container)) {
        throw "No se encontró la carpeta del firmador en '$source'."
    }

    $files = Get-ChildItem -LiteralPath $source -Recurse -File -Force -ErrorAction SilentlyContinue
    if (-not $files) {
        throw "La carpeta del firmador '$source' no contiene archivos."
    }

    $extrasRoot = Join-Path $repoRoot 'extras'
    $extrasDir = Join-Path $extrasRoot 'firmador'
    if (Test-Path -LiteralPath $extrasDir) {
        Get-ChildItem -LiteralPath $extrasDir -Force | Remove-Item -Force -Recurse
    } else {
        New-Item -ItemType Directory -Path $extrasDir -Force | Out-Null
    }

    Write-Host "Copiando firmador a $extrasDir..."
    Get-ChildItem -LiteralPath $source -Force | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $extrasDir -Recurse -Force
    }

    $uploads = Join-Path $extrasDir 'uploads'
    if (-not (Test-Path -LiteralPath $uploads)) {
        New-Item -ItemType Directory -Path $uploads -Force | Out-Null
    }
}

$AppVersion = Get-AppVersion -Requested $AppVersion
$pythonExe = Resolve-Python -Explicit $PythonPath
$isccExe = Resolve-ISCC -Explicit $ISCCPath

Write-Host "Versión del instalador: $AppVersion"
Write-Host "Python: $pythonExe"
Write-Host "Inno Setup: $isccExe"

Copy-SignerToExtras

$distDir = Join-Path $repoRoot 'dist/InventarioFarmacia'
if (Test-Path -LiteralPath $distDir) {
    Write-Host 'Limpiando build previo de PyInstaller...'
    Remove-Item -LiteralPath $distDir -Recurse -Force
}

Write-Host "Ejecutando PyInstaller en modo '$Mode'..."
$pyinstallerArgs = @('setup.py', '--mode', $Mode, '--bundle', 'onedir')
& $pythonExe @pyinstallerArgs
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller finalizó con código $LASTEXITCODE."
}

if (-not (Test-Path -LiteralPath $distDir -PathType Container)) {
    throw "No se generó el directorio '$distDir'."
}

$exePath = Join-Path $distDir 'InventarioFarmacia.exe'
if (-not (Test-Path -LiteralPath $exePath)) {
    throw "No se encontró el ejecutable generado: $exePath"
}

$bundledSigner = Join-Path $distDir 'extras/firmador'
if (-not (Test-Path -LiteralPath $bundledSigner -PathType Container)) {
    throw "El bundle no contiene la carpeta del firmador esperada ('$bundledSigner')."
}

if (-not (Get-ChildItem -LiteralPath $bundledSigner -File -Recurse -Force -ErrorAction SilentlyContinue)) {
    throw 'La carpeta del firmador dentro del bundle está vacía.'
}

$issPath = Join-Path $repoRoot 'installer/vertexdte.iss'
if (-not (Test-Path -LiteralPath $issPath -PathType Leaf)) {
    throw "No se encontró el script de Inno Setup: $issPath"
}

$innoArgs = @("/DAppVersion=$AppVersion")
$resolvedOutput = $null
if ($OutputDir) {
    $resolvedOutput = (Resolve-Path -LiteralPath (New-Item -ItemType Directory -Path $OutputDir -Force).FullName).Path
    $innoArgs += ('/DOutputDir="{0}"' -f $resolvedOutput)
}
$innoArgs += $issPath

Write-Host 'Compilando instalador con Inno Setup...'
& $isccExe @innoArgs
if ($LASTEXITCODE -ne 0) {
    throw "ISCC.exe finalizó con código $LASTEXITCODE."
}

$installerDir = if ($resolvedOutput) { $resolvedOutput } else { Join-Path $repoRoot 'build/installer' }
$expectedInstaller = Join-Path $installerDir "VertexDTE-Setup-$AppVersion.exe"
if (Test-Path -LiteralPath $expectedInstaller -PathType Leaf) {
    Write-Host "Instalador generado: $expectedInstaller"
} else {
    Write-Warning "No se encontró el instalador esperado en '$expectedInstaller'."
}

Write-Host 'Proceso finalizado correctamente.'
