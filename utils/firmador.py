import os
import subprocess
from pathlib import Path
from typing import Optional

# Almacena el proceso para poder detenerlo posteriormente
_FIRMADOR_PROC: Optional[subprocess.Popen] = None

def iniciar_firmador() -> subprocess.Popen:
    """Inicia el servicio ``svfe-api-firmador`` usando el JDK empaquetado."""
    base = Path(__file__).resolve().parent.parent / "svfe-api-firmador"
    java_home = base / "vendor" / "jdk"
    env = os.environ.copy()
    env["JAVA_HOME"] = str(java_home)
    env["PATH"] = f"{java_home / 'bin'}{os.pathsep}{env['PATH']}"
    jar = base / "target" / "svfe-api-firmador-0.1.1.jar"
    proc = subprocess.Popen(
        ["java", "-jar", str(jar), "--server.port=8080"],
        cwd=base,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    global _FIRMADOR_PROC
    _FIRMADOR_PROC = proc
    return proc

def detener_firmador() -> None:
    """Detiene el proceso del firmador si está en ejecución."""
    global _FIRMADOR_PROC
    if _FIRMADOR_PROC and _FIRMADOR_PROC.poll() is None:
        _FIRMADOR_PROC.terminate()
        try:
            _FIRMADOR_PROC.wait(timeout=5)
        except Exception:
            _FIRMADOR_PROC.kill()
    _FIRMADOR_PROC = None
