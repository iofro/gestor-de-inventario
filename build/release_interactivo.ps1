param(
    [string]$OutputDir,
    [string]$Signer,
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
        }
    }

    return '1.0.0'
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

    if ($folderDialog.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) {
        throw 'Operación cancelada: no se seleccionó carpeta de salida.'
    }
    $OutputDir = $folderDialog.SelectedPath

    $fileDialog = New-Object System.Windows.Forms.OpenFileDialog
    $fileDialog.Title = 'Selecciona el archivo del firmador'
    $fileDialog.Filter = 'Todos los archivos (*.*)|*.*'
    if ($Signer) {
        try {
            $fileDialog.InitialDirectory = (Split-Path (Resolve-Path $Signer -ErrorAction Stop).Path -Parent)
        } catch {
            $fileDialog.InitialDirectory = $repoRoot
        }
    }

    if ($fileDialog.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) {
        throw 'Operación cancelada: no se seleccionó el firmador.'
    }
    $Signer = $fileDialog.FileName

    $defaultVersion = Get-DefaultVersion -Current $null
    if (-not $Version) {
        Add-Type -AssemblyName Microsoft.VisualBasic
        $inputVersion = [Microsoft.VisualBasic.Interaction]::InputBox('Versión a publicar:', 'Vertex DTE', $defaultVersion)
        if ([string]::IsNullOrWhiteSpace($inputVersion)) {
            $Version = $defaultVersion
        } else {
            $Version = $inputVersion.Trim()
        }
    } else {
        $Version = $Version.Trim()
    }
} else {
    if (-not $OutputDir) {
        throw 'Debe especificar -OutputDir cuando usa -NoUI.'
    }
    if (-not $Signer) {
        throw 'Debe especificar -Signer cuando usa -NoUI.'
    }
    $Version = Get-DefaultVersion -Current $Version
}

$OutputDir = (Resolve-Path -LiteralPath (New-Item -ItemType Directory -Path $OutputDir -Force).FullName).Path
$Signer = (Resolve-Path -LiteralPath $Signer).Path

Write-Host "Versión objetivo: $Version"
Write-Host "Directorio de salida: $OutputDir"
Write-Host "Firmador seleccionado: $Signer"

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
if (Test-Path $extrasDir) {
    Write-Host 'Limpiando firmador previo...'
    Get-ChildItem -Path $extrasDir -Recurse -Force | Remove-Item -Force -Recurse
} else {
    New-Item -ItemType Directory -Path $extrasDir -Force | Out-Null
}

Copy-Item -LiteralPath $Signer -Destination $extrasDir -Force
$signerFileName = Split-Path $Signer -Leaf

Write-Host 'Ejecutando PyInstaller...'
& $pythonExe -m PyInstaller (Join-Path $repoRoot 'build/VertexDTE.spec')

$distDir = Join-Path $repoRoot 'dist/VertexDTE'
if (-not (Test-Path $distDir)) {
    throw "No se encontró la carpeta generada por PyInstaller ($distDir)."
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
    Compress-Archive -Path $distFolder -DestinationPath $zipPath
} finally {
    Pop-Location
}

$installerPath = $null
$innosetup = Get-Command 'ISCC.exe' -ErrorAction SilentlyContinue
if ($innosetup) {
    Write-Host 'Compilando instalador con Inno Setup...'
    $issFile = Join-Path $repoRoot 'build/VertexDTE.iss'
    & $innosetup.Path "/DAppVersion=$Version" "/DOutputDir=$OutputDir" $issFile
    $expectedInstaller = Join-Path $OutputDir "VertexDTE-Setup-$Version.exe"
    if (Test-Path $expectedInstaller) {
        $installerPath = $expectedInstaller
    } else {
        Write-Warning "Inno Setup terminó sin generar $expectedInstaller. Revisa la salida para más detalles."
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
Write-Host "Firmador empaquetado en: dist/VertexDTE/extras/firmador/$signerFileName"
