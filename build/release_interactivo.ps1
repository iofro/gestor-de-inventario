param(
    [switch]$NoUI,
    [string]$OutputDir,
    [string]$Signer,
    [string]$Version
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Get-DefaultVersion {
    param([string]$VersionFile)
    if (Test-Path -LiteralPath $VersionFile) {
        foreach ($line in Get-Content -LiteralPath $VersionFile) {
            if ($line -match '^\s*version\s*=\s*(.+)') {
                return $Matches[1].Trim()
            }
        }
    }
    return '1.0.0'
}

$repoRoot = Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')
Set-Location -LiteralPath $repoRoot

$defaultVersion = Get-DefaultVersion -VersionFile (Join-Path $repoRoot 'VERSION')

if ($NoUI) {
    if (-not $OutputDir) {
        throw 'Debe especificar -OutputDir en modo -NoUI.'
    }
    if (-not $Signer) {
        throw 'Debe especificar -Signer en modo -NoUI.'
    }
    if (-not $Version) {
        $Version = $defaultVersion
    }
} else {
    Add-Type -AssemblyName System.Windows.Forms

    if (-not $OutputDir) {
        $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
        $dialog.Description = 'Selecciona la carpeta donde se guardarán los artefactos'
        if ($dialog.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) {
            Write-Warning 'Operación cancelada.'
            exit 1
        }
        $OutputDir = $dialog.SelectedPath
    }

    if (-not $Signer) {
        $open = New-Object System.Windows.Forms.OpenFileDialog
        $open.Title = 'Selecciona el ejecutable o archivo del firmador'
        $open.Filter = 'Todos los archivos (*.*)|*.*'
        if ($open.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) {
            Write-Warning 'Operación cancelada.'
            exit 1
        }
        $Signer = $open.FileName
    }

    if (-not $Version) {
        $input = Read-Host "Versión a publicar (Enter para $defaultVersion)"
        if ([string]::IsNullOrWhiteSpace($input)) {
            $Version = $defaultVersion
        } else {
            $Version = $input.Trim()
        }
    }
}

$OutputDir = (Resolve-Path -LiteralPath $OutputDir).Path
$SignerPath = (Resolve-Path -LiteralPath $Signer).Path
$Version = $Version.Trim()
if (-not $Version) {
    throw 'La versión no puede estar vacía.'
}

$sanitizedVersion = [System.Text.RegularExpressions.Regex]::Replace($Version, '[^0-9A-Za-z._-]', '_')

New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null

$venvPath = Join-Path $repoRoot '.venv-release'
if (-not (Test-Path -LiteralPath $venvPath)) {
    python -m venv $venvPath
}
$venvPython = Join-Path $venvPath 'Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPython)) {
    throw 'No se pudo localizar el intérprete de Python en el entorno virtual.'
}

$extrasRoot = Join-Path $repoRoot 'extras'
$firmadorDir = Join-Path $extrasRoot 'firmador'
$firmadorTarget = Join-Path $firmadorDir (Split-Path -Path $SignerPath -Leaf)
$firmadorDirExisted = Test-Path -LiteralPath $firmadorDir
$firmadorAlreadyPresent = Test-Path -LiteralPath $firmadorTarget

New-Item -ItemType Directory -Path $firmadorDir -Force | Out-Null
Copy-Item -LiteralPath $SignerPath -Destination $firmadorTarget -Force

try {
    & $venvPython -m pip install --upgrade pip wheel
    & $venvPython -m pip install -r (Join-Path $repoRoot 'requirements.txt')
    & $venvPython -m pip install pyinstaller appdirs certifi

    Remove-Item -LiteralPath (Join-Path $repoRoot 'dist') -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath (Join-Path $repoRoot 'build' 'VertexDTE') -Recurse -Force -ErrorAction SilentlyContinue

    & $venvPython -m PyInstaller --noconfirm --clean (Join-Path $repoRoot 'build' 'VertexDTE.spec')

    $exePath = Join-Path $repoRoot 'dist\VertexDTE\VertexDTE.exe'
    if (-not (Test-Path -LiteralPath $exePath)) {
        throw 'No se generó VertexDTE.exe. Revisa la salida de PyInstaller.'
    }

    $zipPath = Join-Path $OutputDir ("VertexDTE-$sanitizedVersion-win64.zip")
    if (Test-Path -LiteralPath $zipPath) {
        Remove-Item -LiteralPath $zipPath -Force
    }
    Compress-Archive -Path (Join-Path $repoRoot 'dist\VertexDTE') -DestinationPath $zipPath -Force

    $innoCommand = Get-Command 'ISCC.exe' -ErrorAction SilentlyContinue
    if (-not $innoCommand) {
        $candidates = @(
            Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe',
            Join-Path ${env:ProgramFiles} 'Inno Setup 6\ISCC.exe'
        ) | Where-Object { $_ }
        foreach ($candidate in $candidates) {
            if (Test-Path -LiteralPath $candidate) {
                $innoCommand = @{ Path = $candidate }
                break
            }
        }
    }

    $setupPath = $null
    if ($innoCommand) {
        $defineVersion = '"/DAppVersion={0}"' -f $Version
        $defineOutput = '"/DOutputDir={0}"' -f $OutputDir
        $arguments = @('/Qp', $defineVersion, $defineOutput, (Join-Path $repoRoot 'build\VertexDTE.iss'))
        & $($innoCommand.Path) $arguments
        $setupPath = Join-Path $OutputDir ("VertexDTE-Setup-$sanitizedVersion.exe")
        if (-not (Test-Path -LiteralPath $setupPath)) {
            Write-Warning 'Inno Setup se ejecutó, pero no se encontró el instalador esperado.'
        }
    } else {
        Write-Warning 'No se encontró ISCC.exe. Se omitió la generación del instalador.'
    }

    Write-Host ''
    Write-Host '==== Artefactos generados ===='
    Write-Host ("Carpeta ejecutable: {0}" -f (Join-Path $repoRoot 'dist\VertexDTE'))
    Write-Host ("ZIP portable: {0}" -f $zipPath)
    if ($setupPath) {
        Write-Host ("Instalador: {0}" -f $setupPath)
    }
}
finally {
    if (-not $firmadorDirExisted) {
        if (Test-Path -LiteralPath $firmadorDir) {
            Remove-Item -LiteralPath $firmadorDir -Recurse -Force
        }
        if (Test-Path -LiteralPath $extrasRoot) {
            $remaining = Get-ChildItem -LiteralPath $extrasRoot -ErrorAction SilentlyContinue
            if (-not $remaining) {
                Remove-Item -LiteralPath $extrasRoot -Force
            }
        }
    } elseif (-not $firmadorAlreadyPresent -and (Test-Path -LiteralPath $firmadorTarget)) {
        Remove-Item -LiteralPath $firmadorTarget -Force
    }
}
