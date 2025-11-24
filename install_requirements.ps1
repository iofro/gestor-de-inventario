param(
    [string]$RequirementsFile = "requirements.txt"
)

Write-Host "Installing requirements from '$RequirementsFile'..."

# Try to find python on PATH (python or py launcher)
$pythonCmd = (Get-Command python -ErrorAction SilentlyContinue)?.Source
if (-not $pythonCmd) { $pythonCmd = (Get-Command py -ErrorAction SilentlyContinue)?.Source }

if (-not $pythonCmd) {
    Write-Error "No Python executable found on PATH."
    Write-Host "If you have Python installed but it's not on PATH, run this script using the full python path, for example:"
    Write-Host "& 'C:\\Users\\ariel\\AppData\\Local\\Programs\\Python\\Python311\\python.exe' -m pip install -r $RequirementsFile"
    exit 1
}

# Upgrade pip first
& $pythonCmd -m pip install --upgrade pip

if (Test-Path $RequirementsFile) {
    & $pythonCmd -m pip install -r $RequirementsFile
    if ($LASTEXITCODE -ne 0) {
        Write-Error "pip returned a non-zero exit code ($LASTEXITCODE). Check the output above for errors."
        exit $LASTEXITCODE
    }
    Write-Host "Requirements installed successfully."
} else {
    Write-Error "Requirements file '$RequirementsFile' not found in current directory."
    exit 1
}
