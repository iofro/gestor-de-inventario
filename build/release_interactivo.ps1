param(
    [string]$OutputDir,
    [string]$SignerDir,
    [string]$Version,
    [switch]$NoUI
)

$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $repoRoot

function Get-DefaultVersion {
    param([string]$Current)

    if ($Current -and $Current.Trim().Length -gt 0) {
        return $Current.Trim()
    }

    $versionFile = Join-Path $repoRoot 'VERSION'
    if (Test-Path $versionFile) {
        foreach ($line in Get-Content -Path $versionFile -ErrorAction SilentlyContinue) {
            $trimmed = $line.Trim()
            if ($trimmed -like 'version=*') {
                return $trimmed.Split('=')[-1].Trim()
            }
            if ($trimmed -and $trimmed -notlike '#*') {
                return $trimmed
            }
        }
    }

    return '1.0.0'
}

function Resolve-SignerDirectory {
    param([string]$Path)

    if (-not $Path) {
        throw 'No se especificó la carpeta del firmador.'
    }

    try {
        $resolved = (Resolve-Path -LiteralPath $Path -ErrorAction Stop).Path
    } catch {
        throw "No se pudo acceder a la carpeta del firmador '$Path'."
    }

    if (-not (Test-Path -LiteralPath $resolved -PathType Container)) {
        throw "La ruta '$resolved' no es una carpeta válida para el firmador."
    }

    $items = Get-ChildItem -LiteralPath $resolved -Force -Recurse -File -ErrorAction SilentlyContinue
    if (-not $items) {
        throw "La carpeta del firmador '$resolved' está vacía."
    }

    return $resolved
}

if (-not $NoUI) {
    Add-Type -AssemblyName System.Windows.Forms

    $folderDialog = New-Object System.Windows.Forms.FolderBrowserDialog
    $folderDialog.Description = 'Selecciona la carpeta donde se guardarán los artefactos.'
    if ($OutputDir) {
        try {
            $folderDialog.SelectedPath = (Resolve-Path $OutputDir -ErrorAction Stop).Path
        } catch {
            $folderDialog.SelectedPath = [Environment]::GetFolderPath('Desktop')
        }
    }

    Write-Host 'Seleccionando carpeta de salida...'
    if ($folderDialog.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) {
        Write-Error 'Operación cancelada: no se seleccionó carpeta de salida.'
        throw 'Operación cancelada: no se seleccionó carpeta de salida.'
    }
    $OutputDir = $folderDialog.SelectedPath
    Write-Host "Carpeta elegida: $OutputDir"

    $signerDialog = New-Object System.Windows.Forms.FolderBrowserDialog
    $signerDialog.Description = 'Selecciona la carpeta raíz del firmador.'
    if ($SignerDir) {
        try {
            $signerDialog.SelectedPath = (Resolve-Path $SignerDir -ErrorAction Stop).Path
        } catch {
            $signerDialog.SelectedPath = $repoRoot
        }
    }

    Write-Host 'Seleccionando firmador...'
    if ($signerDialog.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) {
        Write-Error 'Operación cancelada: no se seleccionó la carpeta del firmador.'
        throw 'Operación cancelada: no se seleccionó la carpeta del firmador.'
    }
    $SignerDir = $signerDialog.SelectedPath
    Write-Host "Firmador elegido: $SignerDir"

    $defaultVersion = Get-DefaultVersion -Current $null
    if (-not $Version) {
        Add-Type -AssemblyName Microsoft.VisualBasic
        Write-Host 'Solicitando versión a publicar...'
        $inputVersion = [Microsoft.VisualBasic.Interaction]::InputBox('Versión a publicar:', 'Vertex DTE', $defaultVersion)
        if ([string]::IsNullOrWhiteSpace($inputVersion)) {
            $Version = $defaultVersion
            Write-Host "Se usará la versión predeterminada: $Version"
        } else {
            $Version = $inputVersion.Trim()
            Write-Host "Versión ingresada: $Version"
        }
    } else {
        $Version = $Version.Trim()
    }
} else {
    if (-not $OutputDir) {
        throw 'Debe especificar -OutputDir cuando usa -NoUI.'
    }
    if (-not $SignerDir) {
        throw 'Debe especificar -SignerDir cuando usa -NoUI.'
    }
    $Version = Get-DefaultVersion -Current $Version
}

$OutputDir = (Resolve-Path -LiteralPath (New-Item -ItemType Directory -Path $OutputDir -Force).FullName).Path
$SignerDir = Resolve-SignerDirectory -Path $SignerDir

Write-Host "Versión objetivo: $Version"
Write-Host "Directorio de salida: $OutputDir"
Write-Host "Carpeta del firmador: $SignerDir"

$pythonCmd = Get-Command python -ErrorAction Stop
$venvPath = Join-Path $repoRoot '.venv-release'

if (-not (Test-Path $venvPath)) {
    Write-Host 'Creando entorno virtual...'
    & $pythonCmd.Path -m venv $venvPath
}

$pythonExe = Join-Path $venvPath 'Scripts/python.exe'
if (-not (Test-Path $pythonExe)) {
    throw "No se encontró el intérprete de Python en el entorno virtual ($pythonExe)."
}

Write-Host 'Actualizando pip y dependencias...'
& $pythonExe -m pip install --upgrade pip | Out-String | Write-Verbose
& $pythonExe -m pip install -r (Join-Path $repoRoot 'requirements.txt') | Out-String | Write-Verbose
& $pythonExe -m pip install pyinstaller appdirs certifi | Out-String | Write-Verbose

$extrasRoot = Join-Path $repoRoot 'extras'
$extrasDir = Join-Path $extrasRoot 'firmador'
New-Item -ItemType Directory -Path $extrasRoot -Force | Out-Null
if (Test-Path $extrasDir) {
    Write-Host 'Limpiando firmador previo...'
    Get-ChildItem -Path $extrasDir -Force | Remove-Item -Force -Recurse
} else {
    New-Item -ItemType Directory -Path $extrasDir -Force | Out-Null
}

Write-Host "Copiando firmador desde '$SignerDir'..."
Get-ChildItem -LiteralPath $SignerDir -Force | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination $extrasDir -Recurse -Force
}

if (-not (Get-ChildItem -Path $extrasDir -Force -Recurse -File -ErrorAction SilentlyContinue)) {
    throw 'No se copiaron archivos del firmador. Revisa los permisos de la carpeta seleccionada.'
}

$bundleSignerPath = Join-Path $repoRoot 'dist/VertexDTE/extras/firmador'

try {
    Write-Host 'Ejecutando PyInstaller...'
    & $pythonExe -m PyInstaller (Join-Path $repoRoot 'build/VertexDTE.spec')

    $distDir = Join-Path $repoRoot 'dist/VertexDTE'
    if (-not (Test-Path $distDir)) {
        throw "No se encontró la carpeta generada por PyInstaller (`"$distDir`")."
    }

    if (-not (Test-Path $bundleSignerPath)) {
        throw "El bundle no contiene la carpeta del firmador esperada (`"$bundleSignerPath`")."
    }

    $bundledFiles = Get-ChildItem -Path $bundleSignerPath -Recurse -File -Force -ErrorAction SilentlyContinue
    if (-not $bundledFiles) {
        throw 'La carpeta del firmador dentro del bundle está vacía.'
    }

    $zipName = "VertexDTE-$Version-win64.zip"
    $zipPath = Join-Path $OutputDir $zipName
    if (Test-Path $zipPath) {
        Remove-Item -LiteralPath $zipPath -Force
    }

    Write-Host 'Comprimiendo distribución onedir...'
    $distParent = Split-Path $distDir -Parent
    $distFolder = Split-Path $distDir -Leaf
    Push-Location $distParent
    try {
        Compress-Archive -Path $distFolder -DestinationPath $zipPath -Force
    } finally {
        Pop-Location
    }

    $installerPath = $null
    $innosetup = Get-Command 'ISCC.exe' -ErrorAction SilentlyContinue
    if ($innosetup) {
        Write-Host 'Compilando instalador con Inno Setup...'
        $issFile = Join-Path $repoRoot 'build/VertexDTE.iss'
        & $innosetup.Path "/DAppVersion=$Version" "/DOutputDir=$([string]::Format('"{0}"', $OutputDir))" $issFile
        $expectedInstaller = Join-Path $OutputDir "VertexDTE-Setup-$Version.exe"
        if (Test-Path $expectedInstaller) {
            $installerPath = $expectedInstaller
        } else {
            Write-Warning "Inno Setup terminó sin generar `"$expectedInstaller`". Revisa la salida para más detalles."
        }
    } else {
        Write-Warning 'No se encontró ISCC.exe en el PATH. Se omitió la generación del instalador.'
    }

    Write-Host ''
    Write-Host 'Artefactos generados:'
    Write-Host "  Ejecutable onedir: $distDir"
    Write-Host "  Paquete ZIP:      $zipPath"
    if ($installerPath) {
        Write-Host "  Instalador:       $installerPath"
    }
    Write-Host ''
    Write-Host "Firmador empaquetado en: $bundleSignerPath"
} finally {
    if (Test-Path $extrasDir) {
        Write-Host 'Limpiando carpeta temporal del firmador...'
        Get-ChildItem -Path $extrasDir -Force | Remove-Item -Force -Recurse
    }
}
