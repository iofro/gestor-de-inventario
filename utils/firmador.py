import os
import socket
import subprocess
import logging
from pathlib import Path
from typing import Optional

# Almacena el proceso para poder detenerlo posteriormente
_FIRMADOR_PROC: Optional[subprocess.Popen] = None

FIRMADOR_HOST = "127.0.0.1"
FIRMADOR_PORT = 8080
logger = logging.getLogger(__name__)


def firmador_activo() -> bool:
    """Comprueba si el firmador ya está en ejecución."""
    try:
        with socket.create_connection((FIRMADOR_HOST, FIRMADOR_PORT), timeout=1):
            return True
    except OSError:
        return False

def iniciar_firmador() -> subprocess.Popen:
    """Inicia el servicio ``svfe-api-firmador`` usando el JDK empaquetado."""
    if firmador_activo():
        raise RuntimeError(
            "El firmador ya está corriendo, no es necesario volver a ejecutarlo."
        )

    base = Path(__file__).resolve().parent.parent / "svfe-api-firmador"
    java_home = base / "vendor" / "jdk"
    java_bin = java_home / "bin" / "java.exe"
    jar = base / "target" / "svfe-api-firmador-0.1.1.jar"

    msg = (
        f"FIRMADOR.START: cwd={os.getcwd()} base={base} java={java_bin} "
        f"exists_java={java_bin.exists()} jar={jar} exists_jar={jar.exists()}"
    )
    logger.info(msg)
    print(msg)

    if not java_bin.exists():
        raise FileNotFoundError(f"No se encontró Java en {java_bin}")
    if not jar.exists():
        raise FileNotFoundError(f"No se encontró el jar del firmador en {jar}")

    env = os.environ.copy()
    env["JAVA_HOME"] = str(java_home)
    env["PATH"] = f"{java_home / 'bin'}{os.pathsep}{env.get('PATH','')}"
    cmd = [str(java_bin), "-jar", str(jar), "--server.port=8080"]
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=base,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError as exc:
        logger.error(
            "FIRMADOR.POPEN.ERROR cmd=%s cwd=%s PATH=%s JAVA_HOME=%s exc=%s",
            cmd,
            base,
            env.get("PATH"),
            env.get("JAVA_HOME"),
            exc,
        )
        print(
            "FIRMADOR.POPEN.ERROR",
            f"cmd={cmd}",
            f"cwd={base}",
            f"PATH={env.get('PATH')}",
            f"JAVA_HOME={env.get('JAVA_HOME')}",
            f"exc={exc}",
        )
        raise
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
