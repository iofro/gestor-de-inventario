$ErrorActionPreference = "Stop"

if (Test-Path .venv) {
    Remove-Item .venv -Recurse -Force
}
python -m venv .venv
. .\.venv\Scripts\Activate.ps1
pip install -U pip wheel
pip install -r requirements.txt
pip install pyinstaller appdirs certifi
pyinstaller build/VertexDTE.spec --noconfirm --clean

$exe = Join-Path -Path "dist/VertexDTE" -ChildPath "VertexDTE.exe"
if (-not (Test-Path $exe)) {
    throw "No se encontró $exe"
}

try {
    $process = Start-Process -FilePath $exe -PassThru -ErrorAction Stop
    Start-Sleep -Seconds 5
    if ($process.HasExited) {
        Write-Warning "VertexDTE.exe salió inmediatamente con código $($process.ExitCode)."
    } else {
        Write-Host "VertexDTE.exe inició correctamente (proceso PID $($process.Id))."
        Stop-Process -Id $process.Id -Force
    }
} catch {
    throw "No se pudo iniciar $exe: $($_.Exception.Message)"
}

Write-Host "EXE listo en dist/VertexDTE/"
