$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repoRoot

python -m venv .venv
. .\.venv\Scripts\Activate.ps1
python -m pip install -U pip wheel
pip install -r requirements.txt
pip install pyinstaller appdirs certifi

$iconPath = Join-Path $repoRoot "assets/app.ico"
$iconB64Path = Join-Path $repoRoot "assets/app.ico.b64"
if (-not (Test-Path $iconPath)) {
    if (-not (Test-Path $iconB64Path)) {
        throw "No se encontró $iconB64Path para generar el icono"
    }
    $iconBytes = [Convert]::FromBase64String((Get-Content $iconB64Path -Raw))
    [IO.File]::WriteAllBytes($iconPath, $iconBytes)
}

pyinstaller build/VertexDTE.spec --noconfirm --clean

$exePath = Join-Path $repoRoot "dist/VertexDTE/VertexDTE.exe"
if (-not (Test-Path $exePath)) {
    throw "No se encontró $exePath"
}

Write-Host "Ejecutable generado en $exePath"
try {
    $process = Start-Process -FilePath $exePath -PassThru -WindowStyle Hidden
    Start-Sleep -Seconds 5
    if (-not $process.HasExited) {
        Stop-Process -Id $process.Id -Force
    }
    Write-Host "VertexDTE.exe inició correctamente (proceso finalizado)."
} catch {
    throw "No se pudo iniciar VertexDTE.exe: $($_.Exception.Message)"
}
