[CmdletBinding()]
param(
    [ValidateSet('full', 'update')]
    [string]$Mode = 'full',
    [string]$AppVersion,
    [string]$PythonPath,
    [string]$ISCCPath,
    [string]$OutputDir,
    [switch]$SanitizeInstaller,
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

function Test-InstallerScript {
    param([string]$ScriptPath)

    if (-not (Test-Path -LiteralPath $ScriptPath -PathType Leaf)) {
        throw "No se encontró el script de Inno Setup: $ScriptPath"
    }

    $bytes = [System.IO.File]::ReadAllBytes($ScriptPath)
    $hasUtf8Bom = $false
    if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) {
        $hasUtf8Bom = $true
    }

    if ($hasUtf8Bom) {
        Write-Error 'El script contiene un BOM UTF-8 (U+FEFF) al inicio. Guárdelo sin BOM.'
    }

    $encoding = [System.Text.Encoding]::UTF8
    $text = $encoding.GetString($bytes)
    if ($hasUtf8Bom) {
        $text = $encoding.GetString($bytes, 3, $bytes.Length - 3)
    }

    $lines = $text -split "`r?`n"
    $invalidDirectives = @()
    $forbiddenSequences = @()
    $indentedDirectives = @()
    $nbspLines = @()
    $lineNumber = 0
    $validDirectivePattern = '^#(define|undef|ifdef|ifndef|if|else|endif|include|file|emit|append|expr|pragma)\b'
    $invalidDirectivePrefixPattern = '^\s*#'
    $indentedDirectivePattern = '^\s+#(define|undef|ifdef|ifndef|if|else|endif|include|file|emit|append|expr|pragma)\b'
    $forbiddenSequencePattern = '^\s*#13#10'
    $nbspChar = [char]0x00A0

    foreach ($line in $lines) {
        $lineNumber++
        $lineForChecks = $line.Replace([char]0xFEFF, '').Replace($nbspChar, ' ')

        if ($line.Contains($nbspChar)) {
            $nbspLines += [PSCustomObject]@{ LineNumber = $lineNumber; Text = $line }
        }

        if ($lineForChecks -match $invalidDirectivePrefixPattern -and -not ($lineForChecks -match $validDirectivePattern)) {
            $invalidDirectives += [PSCustomObject]@{ LineNumber = $lineNumber; Text = $line }
        }

        if ($lineForChecks -match $indentedDirectivePattern) {
            $indentedDirectives += [PSCustomObject]@{ LineNumber = $lineNumber; Text = $line }
        }

        if ($lineForChecks -match $forbiddenSequencePattern) {
            $forbiddenSequences += [PSCustomObject]@{ LineNumber = $lineNumber; Text = $line }
        }
    }

    $hasErrors = $false
    if ($hasUtf8Bom) { $hasErrors = $true }
    if ($nbspLines) { $hasErrors = $true }
    if ($invalidDirectives) { $hasErrors = $true }
    if ($forbiddenSequences) { $hasErrors = $true }
    if ($indentedDirectives) { $hasErrors = $true }

    if (-not $hasErrors) {
        return
    }

    if ($invalidDirectives) {
        Write-Error 'Se encontraron líneas que comienzan con "#" y no son directivas ISPP válidas:'
        foreach ($item in $invalidDirectives) {
            Write-Error ("Línea {0}: {1}" -f $item.LineNumber, $item.Text)
        }
    }

    if ($indentedDirectives) {
        Write-Error 'Se encontraron directivas ISPP con espacios antes del carácter "#":'
        foreach ($item in $indentedDirectives) {
            Write-Error ("Línea {0}: {1}" -f $item.LineNumber, $item.Text)
        }
    }

    if ($forbiddenSequences) {
        Write-Error 'Se encontraron secuencias prohibidas al inicio de línea:'
        foreach ($item in $forbiddenSequences) {
            Write-Error ("Línea {0}: {1}" -f $item.LineNumber, $item.Text)
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

$scriptForCompilation = $issPath
$temporaryScript = $null

if ($SanitizeInstaller -or $NoDefines) {
    $temporaryScript = Join-Path ([System.IO.Path]::GetTempPath()) ("vertexdte_{0}.iss" -f [Guid]::NewGuid().ToString('N'))
    Sanitize-InstallerScript -ScriptPath $issPath -DestinationPath $temporaryScript | Out-Null
    $scriptForCompilation = $temporaryScript
}

if ($NoDefines) {
    $injectedDefines = "#define AppVersion \"1.0.0\"`r`n#define BuildOutputDir \"installer\\build\\installer\"`r`n"
    $existingContent = Get-Content -LiteralPath $scriptForCompilation -Raw
    Set-Content -LiteralPath $scriptForCompilation -Value ($injectedDefines + $existingContent) -Encoding utf8NoBOM
}

$innoArgs = @()
if ($scriptForCompilation -eq $issPath) {
    $innoArgs += $issRelativePath
} else {
    $innoArgs += $scriptForCompilation
}

if (-not $NoDefines) {
    $innoArgs += "/DAppVersion=$AppVersion"
    $innoArgs += ('/DBuildOutputDir="{0}"' -f $buildOutputDefine)
}

Write-Host 'Compilando instalador con Inno Setup...'
$innoOutput = & $isccExe @innoArgs 2>&1
if ($innoOutput) {
    $innoOutput | ForEach-Object { Write-Host $_ }
}

if ($LASTEXITCODE -ne 0) {
    Write-Error 'ISCC.exe produjo errores:'
    if ($innoOutput) {
        $innoOutput | ForEach-Object { Write-Error $_ }
    }

    $errorText = $innoOutput -join "`n"
    $lineMatch = [regex]::Match($errorText, 'Error on line\s+(\d+)')
    if ($lineMatch.Success) {
        $errorLine = [int]$lineMatch.Groups[1].Value
        try {
            $scriptLines = Get-Content -LiteralPath $scriptForCompilation
            $startIndex = [Math]::Max(0, $errorLine - 6)
            $endIndex = [Math]::Min($scriptLines.Length - 1, $errorLine + 4)
            Write-Error "Contexto alrededor de la línea $errorLine:"
            for ($i = $startIndex; $i -le $endIndex; $i++) {
                $displayLineNumber = $i + 1
                Write-Error ("{0,5}: {1}" -f $displayLineNumber, $scriptLines[$i])
            }
        } catch {
            Write-Error "No se pudo leer el script para mostrar el contexto: $_"
        }
    }

    if ($temporaryScript -and (Test-Path -LiteralPath $temporaryScript)) {
        Remove-Item -LiteralPath $temporaryScript -Force -ErrorAction SilentlyContinue
    }

    throw "ISCC.exe finalizó con código $LASTEXITCODE."
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
