"""Utilities to send PDF documents to the system print spooler."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys


class PrintError(RuntimeError):
    """Raised when a PDF could not be sent to the printer."""


def send_pdf_to_printer(pdf_path: str, printer_name: str | None = None) -> None:
    """Send ``pdf_path`` to the print spooler.

    Args:
        pdf_path: Absolute path to the PDF file that should be printed.
        printer_name: Optional printer name selected by the user.

    Raises:
        PrintError: If the command required to print the file could not be
            executed or returned an error status.
    """

    if not pdf_path or not os.path.exists(pdf_path):
        raise PrintError("No se encontró el archivo PDF para imprimir.")

    if sys.platform.startswith("win"):
        _print_with_powershell(pdf_path, printer_name)
        return

    command = _build_unix_print_command(pdf_path, printer_name)
    if not command:
        raise PrintError(
            "No se encontró un comando de impresión compatible (lp o lpr)."
        )
    _run_print_command(command)


def _build_unix_print_command(
    pdf_path: str, printer_name: str | None = None
) -> list[str] | None:
    """Build the printing command for Unix-like systems."""

    if shutil.which("lp"):
        command = ["lp"]
        if printer_name:
            command.extend(["-d", printer_name])
        command.append(pdf_path)
        return command

    if shutil.which("lpr"):
        command = ["lpr"]
        if printer_name:
            command.extend(["-P", printer_name])
        command.append(pdf_path)
        return command

    return None


def _run_print_command(command: list[str]) -> None:
    """Execute a system command and raise ``PrintError`` on failure."""

    try:
        subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:  # pragma: no cover - defensive branch
        raise PrintError(f"No se encontró el comando de impresión: {exc}") from exc
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip() if exc.stderr else ""
        stdout = exc.stdout.strip() if exc.stdout else ""
        details = stderr or stdout or str(exc)
        raise PrintError(f"Error al enviar el PDF a la impresora: {details}") from exc


def _powershell_quote(value: str) -> str:
    """Return a PowerShell-escaped literal string."""

    return "'" + value.replace("'", "''") + "'"


def _print_with_powershell(pdf_path: str, printer_name: str | None) -> None:
    """Send the PDF to Windows' print system using PowerShell."""

    powershell = shutil.which("powershell") or shutil.which("powershell.exe")
    if not powershell:
        raise PrintError("No se encontró PowerShell para imprimir el documento.")

    verb = "PrintTo" if printer_name else "Print"
    quoted_path = _powershell_quote(os.path.abspath(pdf_path))
    script_parts = ["$ErrorActionPreference='Stop';"]
    if printer_name:
        quoted_arguments = _powershell_quote(printer_name)
        command = (
            f"$process = Start-Process -FilePath {quoted_path} -Verb {verb!r} "
            f"-ArgumentList {quoted_arguments} -PassThru;"
        )
    else:
        command = (
            f"$process = Start-Process -FilePath {quoted_path} -Verb {verb!r} -PassThru;"
        )
    script_parts.append(command)
    script_parts.append("Wait-Process -Id $process.Id")
    script = " ".join(script_parts)

    try:
        subprocess.run(
            [powershell, "-NoProfile", "-Command", script],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip() if exc.stderr else ""
        stdout = exc.stdout.strip() if exc.stdout else ""
        details = stderr or stdout or str(exc)
        raise PrintError(f"Error al imprimir el documento: {details}") from exc
