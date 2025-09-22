[CmdletBinding()]
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
    param(
        [string]$Current
    )

    if ($Current -and -not [string]::IsNullOrWhiteSpace($Current)) {
        return $Current.Trim()
    }

    $versionFile = Join-Path $repoRoot 'VERSION'
    if (Test-Path $versionFile) {
        foreach ($line in Get-Content -Path $versionFile -ErrorAction SilentlyContinue) {
            $trimmed = $line.Trim()
            if (-not $trimmed) {
                continue
            }

            if ($trimmed -like 'version=*') {
                return $trimmed.Split('=')[-1].Trim()
            }

            if ($trimmed -notlike '#*') {
                return $trimmed
            }
        }
    }

    return '1.0.0'
}

function Resolve-SignerDirectory {
    param(
        [string]$Path
    )

    if (-not $Path) {
        throw 'Debe especificar la carpeta del firmador.'
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

function Resolve-PythonInterpreter {
    $candidates = @()

    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCmd) {
        $candidates += [pscustomobject]@{
            Command     = $pythonCmd.Path
            Arguments   = @()
            Description = 'python'
        }
    }

    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        $candidates += [pscustomobject]@{
            Command     = $pyLauncher.Path
            Arguments   = @('-3.11')
            Description = 'py -3.11'
        }
        $candidates += [pscustomobject]@{
            Command     = $pyLauncher.Path
            Arguments   = @()
            Description = 'py'
        }
    }

    $winApps = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'Microsoft\WindowsApps\python3.11.exe'
    if (Test-Path $winApps) {
        $candidates += [pscustomobject]@{
            Command     = $winApps
            Arguments   = @()
            Description = $winApps
        }
    }

    foreach ($candidate in $candidates) {
        try {
            $output = & $candidate.Command @($candidate.Arguments) -c "import sys;print(sys.executable)"
            if ($LASTEXITCODE -ne 0) {
                continue
            }

            $executable = $null
            if ($output) {
                $executable = $output.Trim().Split("`n")[-1].Trim()
            }

            if ($executable -and (Test-Path -LiteralPath $executable)) {
                Write-Host "Python detectado ($($candidate.Description)): $executable"
                return $executable
            }
        } catch {
            continue
        }
    }

    throw 'No se encontró una instalación de Python compatible. Asegúrate de tener Python 3.11 disponible.'
}

function New-TempCopyOfFolder {
    param([string]$SourceDir)
    $tmp = Join-Path $env:TEMP ("VertexDTE_" + [guid]::NewGuid())
    robocopy $SourceDir $tmp /MIR /NFL /NDL /NJH /NJS /NC /NS | Out-Null
    return $tmp
}

function Compress-DirectoryWithRetry {
    param(
        [string]$SourceDir,
        [string]$ZipPath,
        [int]$MaxAttempts = 8
    )
    # Limpia ZIP previo
    if (Test-Path $ZipPath) { Remove-Item $ZipPath -Force }

    # Copia a TEMP para evitar handles sobre dist\
    $tempDir = New-TempCopyOfFolder -SourceDir $SourceDir
    try {
        for ($i=1; $i -le $MaxAttempts; $i++) {
            try {
                [System.GC]::Collect(); [System.GC]::WaitForPendingFinalizers()
                Start-Sleep -Milliseconds (250 * $i)
                Compress-Archive -Path (Join-Path $tempDir '*') -DestinationPath $ZipPath -Force -ErrorAction Stop
                Write-Host ("ZIP creado en intento {0}: {1}" -f $i, $ZipPath)
                return $true
            } catch {
                $hr = $_.Exception.HResult
                $msg = $_.Exception.Message
                # 0x80070020 = sharing violation
                if ($hr -eq -2147024864 -or $msg -match 'being used by another process') {
                    Write-Warning "ZIP bloqueado (intento $i/$MaxAttempts). Reintentando…"
                    Start-Sleep -Seconds ([math]::Pow(2, [math]::Min($i,5))) # backoff exponencial
                    continue
                } else {
                    throw
                }
            }
        }
        # Fallback .NET si Compress-Archive no logró
        try {
            Add-Type -AssemblyName System.IO.Compression.FileSystem
            [System.IO.Compression.ZipFile]::CreateFromDirectory($tempDir, $ZipPath)
            Write-Host "ZIP creado con fallback .NET: $ZipPath"
            return $true
        } catch {
            Write-Warning "Fallo creando ZIP incluso con fallback: $($_.Exception.Message)"
            return $false
        }
    } finally {
        try { Remove-Item $tempDir -Recurse -Force } catch { }
    }
}

if ($NoUI) {
    if (-not $OutputDir) {
        throw 'Debe especificar -OutputDir cuando usa -NoUI.'
    }
    if (-not $SignerDir) {
        throw 'Debe especificar -SignerDir cuando usa -NoUI.'
    }
    if (-not $Version) {
        throw 'Debe especificar -Version cuando usa -NoUI.'
    }

    $Version = Get-DefaultVersion -Current $Version
} else {
    Add-Type -AssemblyName System.Windows.Forms

    $folderDialog = New-Object System.Windows.Forms.FolderBrowserDialog
    $folderDialog.Description = 'Selecciona la carpeta donde se guardarán los artefactos.'
    if ($OutputDir) {
        try {
            $folderDialog.SelectedPath = (Resolve-Path -LiteralPath $OutputDir -ErrorAction Stop).Path
        } catch {
            $folderDialog.SelectedPath = [Environment]::GetFolderPath('Desktop')
        }
    }

    Write-Host 'Seleccionando carpeta de salida...'
    if ($folderDialog.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) {
        throw 'Operación cancelada: no se seleccionó carpeta de salida.'
    }
    $OutputDir = $folderDialog.SelectedPath
    Write-Host "Carpeta elegida: $OutputDir"

    $signerDialog = New-Object System.Windows.Forms.FolderBrowserDialog
    $signerDialog.Description = 'Selecciona la carpeta raíz del firmador.'
    if ($SignerDir) {
        try {
            $signerDialog.SelectedPath = (Resolve-Path -LiteralPath $SignerDir -ErrorAction Stop).Path
        } catch {
            $signerDialog.SelectedPath = $repoRoot
        }
    }

    Write-Host 'Seleccionando firmador...'
    if ($signerDialog.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) {
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
}

$OutputDir = (Resolve-Path -LiteralPath (New-Item -ItemType Directory -Path $OutputDir -Force).FullName).Path
$SignerDir = Resolve-SignerDirectory -Path $SignerDir

Write-Host "Versión objetivo: $Version"
Write-Host "Directorio de salida: $OutputDir"
Write-Host "Carpeta del firmador: $SignerDir"

$pythonExecutable = Resolve-PythonInterpreter

$venvPath = Join-Path $repoRoot '.venv-release'
if (-not (Test-Path -LiteralPath $venvPath)) {
    Write-Host "Creando entorno virtual en $venvPath..."
    & $pythonExecutable -m venv $venvPath
}

$pythonExe = Join-Path $venvPath 'Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) {
    throw "No se encontró el intérprete de Python en el entorno virtual: $pythonExe"
}

Write-Host 'Actualizando pip...'
& $pythonExe -m pip install --upgrade pip

Write-Host 'Instalando dependencias del proyecto...'
& $pythonExe -m pip install -r (Join-Path $repoRoot 'requirements.txt')

Write-Host 'Instalando herramientas de build...'
& $pythonExe -m pip install pyinstaller appdirs certifi

$extrasRoot = Join-Path $repoRoot 'extras'
$extrasDir = Join-Path $extrasRoot 'firmador'
Write-Host 'Preparando carpeta del firmador...'
New-Item -ItemType Directory -Path $extrasRoot -Force | Out-Null
if (Test-Path -LiteralPath $extrasDir) {
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

$specPath = Join-Path $repoRoot 'build/VertexDTE.spec'
$distDir = Join-Path $repoRoot 'dist/VertexDTE'
$bundleSignerPath = Join-Path $distDir 'extras/firmador'

try {
    Write-Host 'Ejecutando PyInstaller...'
    & $pythonExe -m PyInstaller $specPath --noconfirm --clean

    if (-not (Test-Path -LiteralPath $distDir)) {
        throw "No se encontró la carpeta generada por PyInstaller ('$distDir')."
    }

    if (-not (Test-Path -LiteralPath $bundleSignerPath)) {
        throw "El bundle no contiene la carpeta del firmador esperada ('$bundleSignerPath')."
    }

    $bundledFiles = Get-ChildItem -Path $bundleSignerPath -Recurse -File -Force -ErrorAction SilentlyContinue
    if (-not $bundledFiles) {
        throw 'La carpeta del firmador dentro del bundle está vacía.'
    }

    $zipName = "VertexDTE-$Version-win64.zip"
    $zipPath = Join-Path $OutputDir $zipName
    Write-Host 'Generando archivo ZIP...'
    $zipOk = Compress-DirectoryWithRetry -SourceDir $distDir -ZipPath $zipPath
    if (-not $zipOk) {
        Write-Warning "No se pudo generar el ZIP tras reintentos. Se continúa con el instalador si hay Inno Setup."
    }

    $installerPath = $null
    $innoCommand = Get-Command 'ISCC.exe' -ErrorAction SilentlyContinue
    if (-not $innoCommand) {
        $defaultInnoPaths = @(
            'C:\Program Files (x86)\Inno Setup 6\ISCC.exe',
            'C:\Program Files\Inno Setup 6\ISCC.exe'
        )

        foreach ($defaultPath in $defaultInnoPaths) {
            if (Test-Path -LiteralPath $defaultPath) {
                $innoCommand = [pscustomobject]@{ Path = $defaultPath }
                break
            }
        }
    }

    if ($innoCommand) {
        Write-Host "Compilando instalador con Inno Setup usando '$($innoCommand.Path)'..."
        $issFile = Join-Path $repoRoot 'build/VertexDTE.iss'
        $appVersionArg = "/DAppVersion=$Version"
        $outputDirArg = [string]::Format('/DOutputDir="{0}"', $OutputDir)
        & $innoCommand.Path $appVersionArg $outputDirArg $issFile
        $expectedInstaller = Join-Path $OutputDir "VertexDTE-Setup-$Version.exe"
        if (Test-Path -LiteralPath $expectedInstaller) {
            $installerPath = $expectedInstaller
        } else {
            Write-Warning "Inno Setup terminó sin generar '$expectedInstaller'. Revisa la salida para más detalles."
        }
    } else {
        Write-Warning 'No se encontró ISCC.exe. Se omitió la generación del instalador.'
    }

    Write-Host ''
    Write-Host 'Artefactos generados:'
    Write-Host "  Ejecutable onedir: $distDir"
    if (Test-Path -LiteralPath $zipPath) {
        Write-Host "  Paquete ZIP:      $zipPath"
    } else {
        Write-Warning "  Paquete ZIP no generado. Revisa los mensajes anteriores."
    }
    if ($installerPath) {
        Write-Host "  Instalador:       $installerPath"
    }
    Write-Host ''
    Write-Host "Firmador empaquetado en: $bundleSignerPath"
} finally {
    if (Test-Path -LiteralPath $extrasDir) {
        Write-Host 'Limpiando carpeta temporal del firmador...'
        Get-ChildItem -Path $extrasDir -Force | Remove-Item -Force -Recurse
    }
}
