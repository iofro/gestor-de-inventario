[CmdletBinding()]
param(
    [ValidateSet('full', 'update')]
    [string]$Mode = 'full',
    [string]$AppVersion,
    [string]$PythonPath,
    [string]$ISCCPath,
    [string]$OutputDir,
    [switch]$NoDefines
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

function Sanitize-InstallerScript {
    param([string]$ScriptPath)

    if (-not (Test-Path -LiteralPath $ScriptPath -PathType Leaf)) {
        throw "No se encontró el script de Inno Setup: $ScriptPath"
    }

    $rawContent = [System.IO.File]::ReadAllText($ScriptPath)
    $normalized = $rawContent.Replace([char]0xFEFF, '').Replace([char]0x00A0, ' ')
    $normalized = $normalized.Replace("`r`n", "`n").Replace("`r", "`n")
    $normalized = $normalized.Replace("`n", "`r`n")

    if ($normalized -ne $rawContent) {
        $encoding = New-Object System.Text.UTF8Encoding($false)
        [System.IO.File]::WriteAllText($ScriptPath, $normalized, $encoding)
        Write-Host "Se normalizó el script de Inno Setup: $ScriptPath"
    }
}

function Test-InstallerScript {
    param([string]$ScriptPath)

    if (-not (Test-Path -LiteralPath $ScriptPath -PathType Leaf)) {
        throw "No se encontró el script de Inno Setup: $ScriptPath"
    }

    $rawContent = [System.IO.File]::ReadAllText($ScriptPath)
    $normalizedContent = $rawContent.Replace([char]0xFEFF, '').Replace([char]0x00A0, ' ')
    $lines = $normalizedContent -split "`r?`n"

    $validDirectivePattern = '^#(define|undef|ifdef|ifndef|if|else|endif|include|file|emit|append|expr|pragma)\b'
    $hashAtStartPattern = '^#'
    $forbiddenSequencePattern = '^#13#10'

    $invalidDirectives = @()
    $forbiddenSequences = @()
    $misalignedDirectives = @()

    for ($index = 0; $index -lt $lines.Length; $index++) {
        $lineNumber = $index + 1
        $line = $lines[$index]

        if ($line -match '^\s+#') {
            $misalignedDirectives += [PSCustomObject]@{ LineNumber = $lineNumber; Text = $line }
        }

        if ($line -match $hashAtStartPattern) {
            if ($line -notmatch $validDirectivePattern) {
                $invalidDirectives += [PSCustomObject]@{ LineNumber = $lineNumber; Text = $line }
            }
        }

        if ($line -match $forbiddenSequencePattern) {
            $forbiddenSequences += [PSCustomObject]@{ LineNumber = $lineNumber; Text = $line }
        }
    }

    if ($invalidDirectives -or $forbiddenSequences -or $misalignedDirectives) {
        if ($misalignedDirectives) {
            Write-Error 'Las directivas ISPP deben comenzar en la columna 1:'
            foreach ($item in $misalignedDirectives) {
                Write-Error ("Línea {0}: {1}" -f $item.LineNumber, $item.Text)
            }
        }
        if ($invalidDirectives) {
            Write-Error 'Se encontraron líneas que comienzan con # pero no son directivas válidas:'
            foreach ($item in $invalidDirectives) {
                Write-Error ("Línea {0}: {1}" -f $item.LineNumber, $item.Text)
            }
        }
        if ($forbiddenSequences) {
            Write-Error 'Se encontraron secuencias prohibidas al inicio de línea (#13#10):'
            foreach ($item in $forbiddenSequences) {
                Write-Error ("Línea {0}: {1}" -f $item.LineNumber, $item.Text)
            }
        }
    }

    if ($nbspLines) {
        Write-Error 'Se encontraron caracteres U+00A0 (NBSP) en las siguientes líneas:'
        foreach ($item in $nbspLines) {
            Write-Error ("Línea {0}: {1}" -f $item.LineNumber, $item.Text)
        }
    }

    throw 'El preflight del instalador detectó líneas inválidas en el script de Inno Setup.'
}

function Sanitize-InstallerScript {
    param(
        [string]$ScriptPath,
        [string]$DestinationPath
    )

    if (-not (Test-Path -LiteralPath $ScriptPath -PathType Leaf)) {
        throw "No se encontró el script de Inno Setup: $ScriptPath"
    }

    if (-not $DestinationPath) {
        $DestinationPath = $ScriptPath
    }

    $content = Get-Content -LiteralPath $ScriptPath -Raw
    $content = $content.Replace([char]0xFEFF, '')
    $content = $content.Replace([char]0x00A0, ' ')
    $content = $content -replace "`r?`n", "`n"
    $content = $content -replace "`n", "`r`n"

    Set-Content -LiteralPath $DestinationPath -Value $content -Encoding utf8NoBOM
    return $DestinationPath
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
    $extrasDir = Join-Path $extrasRoot 'svfe-api-firmador'
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

$bundledSigner = Join-Path $distDir '_internal/svfe-api-firmador'
if (-not (Test-Path -LiteralPath $bundledSigner -PathType Container)) {
    throw "El bundle no contiene la carpeta del firmador esperada ('$bundledSigner')."
}

if (-not (Get-ChildItem -LiteralPath $bundledSigner -File -Recurse -Force -ErrorAction SilentlyContinue)) {
    throw 'La carpeta del firmador dentro del bundle está vacía.'
}

$issRelativePath = 'installer\vertexdte.iss'
$issPath = Join-Path $repoRoot $issRelativePath
Sanitize-InstallerScript -ScriptPath $issPath
Test-InstallerScript -ScriptPath $issPath

$defaultBuildOutputRel = 'installer\build\installer'
$buildOutputDefine = $defaultBuildOutputRel
$resolvedOutput = $null

if ($NoDefines) {
    $resolvedOutput = Join-Path $repoRoot $defaultBuildOutputRel
    if (-not (Test-Path -LiteralPath $resolvedOutput)) {
        New-Item -ItemType Directory -Path $resolvedOutput -Force | Out-Null
    }
} elseif ($OutputDir) {
    $resolvedOutput = (Resolve-Path -LiteralPath (New-Item -ItemType Directory -Path $OutputDir -Force).FullName).Path
    $buildOutputDefine = $resolvedOutput
} else {
    $resolvedOutput = Join-Path $repoRoot $defaultBuildOutputRel
    if (-not (Test-Path -LiteralPath $resolvedOutput)) {
        New-Item -ItemType Directory -Path $resolvedOutput -Force | Out-Null
    }
}

$compileScriptPath = $issPath
$scriptArgument = $issRelativePath
$tempIssPath = $null

if ($NoDefines) {
    Write-Host 'Se habilitó el modo -NoDefines; se usarán definiciones predeterminadas en un script temporal.'
    $tempIssPath = Join-Path ([System.IO.Path]::GetTempPath()) ("vertexdte_{0}.iss" -f ([System.Guid]::NewGuid().ToString('N')))
    $defaultDefines = @'
#define AppVersion "1.0.0"
#define BuildOutputDir "installer\build\installer"
'@ + "`r`n"
    $originalContent = [System.IO.File]::ReadAllText($issPath)
    $encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($tempIssPath, $defaultDefines + $originalContent, $encoding)
    $compileScriptPath = $tempIssPath
    $scriptArgument = $compileScriptPath
}

try {
    $innoArgs = @($scriptArgument)
    if (-not $NoDefines) {
        $innoArgs += "/DAppVersion=$AppVersion"
        $innoArgs += ('/DBuildOutputDir="{0}"' -f $buildOutputDefine)
    }

    Write-Host 'Compilando instalador con Inno Setup...'
    $innoOutput = & $isccExe @innoArgs 2>&1
    $exitCode = $LASTEXITCODE
    if ($innoOutput) {
        $innoOutput | ForEach-Object { Write-Host $_ }
    }

    if ($exitCode -ne 0) {
        Write-Error 'ISCC.exe produjo errores:'
        if ($innoOutput) {
            $innoOutput | ForEach-Object { Write-Error $_ }
        }

        $errorLines = @()
        if ($innoOutput) {
            foreach ($line in $innoOutput) {
                if ($line -match 'Error on line ([0-9]+)') {
                    $errorLines += [int]$Matches[1]
                }
            }
        }

        if ($errorLines.Count -gt 0) {
            $contextSource = $compileScriptPath
            $scriptLines = [System.IO.File]::ReadAllLines($contextSource)
            foreach ($lineNumber in ($errorLines | Sort-Object -Unique)) {
                $start = [Math]::Max($lineNumber - 5, 1)
                $finish = [Math]::Min($lineNumber + 5, $scriptLines.Length)
                Write-Error ("Contexto para la línea {0}:" -f $lineNumber)
                for ($i = $start; $i -le $finish; $i++) {
                    $prefix = if ($i -eq $lineNumber) { '>>' } else { '  ' }
                    Write-Error ("{0}{1,5}: {2}" -f $prefix, $i, $scriptLines[$i - 1])
                }
            }
        }

        throw "ISCC.exe finalizó con código $exitCode."
    }
}
finally {
    if ($tempIssPath -and (Test-Path -LiteralPath $tempIssPath)) {
        Remove-Item -LiteralPath $tempIssPath -Force
    }
}

if ($temporaryScript -and (Test-Path -LiteralPath $temporaryScript)) {
    Remove-Item -LiteralPath $temporaryScript -Force -ErrorAction SilentlyContinue
}

$appVersionForOutput = if ($NoDefines) { '1.0.0' } else { $AppVersion }
$expectedInstaller = Join-Path $resolvedOutput "VertexDTE-Setup-$appVersionForOutput.exe"
if (Test-Path -LiteralPath $expectedInstaller -PathType Leaf) {
    Write-Host "Instalador generado: $expectedInstaller"
} else {
    Write-Warning "No se encontró el instalador esperado en '$expectedInstaller'."
}

Write-Host 'Proceso finalizado correctamente.'
