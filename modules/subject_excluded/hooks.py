"""
Hooks opcionales para compras a sujetos excluidos.

Construyen el payload FSE (tipoDte 14) pero no lo firman ni envían.
"""

import json
import logging
from pathlib import Path
from typing import Any

from paths import ensure_user_dir

try:  # Fallback defensivo si el módulo se borra
    from modules.subject_excluded.dte_builder import build_fse_from_compra
except Exception:  # pragma: no cover
    build_fse_from_compra = None

logger = logging.getLogger(__name__)


def _escape_pdf_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _write_stub_pdf(dest: Path, *, titulo: str, lineas: list[str]) -> None:
    """Crea un PDF mínimo (1 página) para acompañar el JSON FSE."""

    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        contenido = f"BT /F1 12 Tf 72 720 Td ({_escape_pdf_text(titulo)}) Tj "
        for linea in lineas:
            contenido += f"0 -14 Td ({_escape_pdf_text(linea)}) Tj "
        contenido += "ET\n"
        content_bytes = contenido.encode("latin-1", "ignore")

        header = b"%PDF-1.4\n"
        objects = [
            b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n",
            b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n",
            b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >> endobj\n",
            b"4 0 obj << /Length " + str(len(content_bytes)).encode("ascii") + b" >> stream\n" + content_bytes + b"endstream endobj\n",
            b"5 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n",
        ]
        offsets = [0]
        current = len(header)
        for obj in objects:
            offsets.append(current)
            current += len(obj)
        body = header + b"".join(objects)

        xref_pos = len(body)
        xref = f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode("ascii")
        for off in offsets[1:]:
            xref += f"{off:010d} 00000 n \n".encode("ascii")
        trailer = b"trailer << /Size " + str(len(offsets)).encode("ascii") + b" /Root 1 0 R >>\nstartxref\n" + str(xref_pos).encode("ascii") + b"\n%%EOF"

        with open(dest, "wb") as fh:
            fh.write(body + xref + trailer)
    except Exception:
        logger.exception("No se pudo generar PDF stub para %s", dest)


def on_subject_excluded_purchase(
    compra_id: int,
    status: str | None = None,
    db: Any = None,
    modo_contingencia: bool | None = None,
    tipo_contingencia: int | None = None,
    motivo_contingencia: str | None = None,
) -> None:
    """Invocado tras registrar una compra a sujeto excluido."""

    try:
        if modo_contingencia is None:
            try:
                from dte import get_default_modo_transmision

                modo_raw = get_default_modo_transmision()
                modo_contingencia = str(modo_raw or "").strip().lower() in {"contingencia", "2", "02"}
            except Exception:
                modo_contingencia = False
        if modo_contingencia and tipo_contingencia is None:
            try:
                from dte import _contingencia_config_from_settings

                tipo_contingencia, motivo_contingencia = _contingencia_config_from_settings()
            except Exception:
                logger.warning(
                    "No se pudo leer tipo_contingencia/motivo_contin desde configuración; "
                    "se omitirá la generación de FSE en contingencia para compra %s",
                    compra_id,
                )
                return
        fse = None
        if callable(build_fse_from_compra) and db is not None:
            fse = build_fse_from_compra(
                db,
                compra_id,
                modo_contingencia=modo_contingencia,
                tipo_contingencia=tipo_contingencia,
                motivo_contingencia=motivo_contingencia,
            )
            # Persistir una copia JSON local del DTE construido
            try:
                output_dir = ensure_user_dir("dtes_sujeto_excluido")
                cg = fse.get("identificacion", {}).get("codigoGeneracion") if isinstance(fse, dict) else None
                filename = f"fse_compra_{compra_id}_{cg or 'sin_codigo'}.json"
                out_path = Path(output_dir) / filename
                with open(out_path, "w", encoding="utf-8") as fh:
                    json.dump(fse, fh, ensure_ascii=False, indent=2)
                # Genera un PDF de referencia con datos clave si no existe uno con el mismo nombre.
                pdf_path = out_path.with_suffix(".pdf")
                ident = fse.get("identificacion", {}) if isinstance(fse, dict) else {}
                numero_control = ident.get("numeroControl") or ""
                fecha_emi = ident.get("fecEmi") or ""
                if not pdf_path.exists():
                    lineas = [
                        f"Compra ID: {compra_id}",
                        f"Codigo generacion: {cg or 'N/D'}",
                        f"Numero control: {numero_control or 'N/D'}",
                        f"Fecha emision: {fecha_emi or 'N/D'}",
                    ]
                    _write_stub_pdf(pdf_path, titulo="Factura sujeto excluido", lineas=lineas)
                logger.info("FSE guardado en %s", out_path)
            except Exception:
                logger.exception("No se pudo guardar el FSE en disco para la compra %s", compra_id)
            logger.info(
                "FSE construido para compra %s (status=%s): codigoGeneracion=%s",
                compra_id,
                status or "PENDIENTE",
                fse.get("identificacion", {}).get("codigoGeneracion") if isinstance(fse, dict) else None,
            )
        else:
            logger.info(
                "Compra sujeto excluido registrada (sin builder activo): id=%s status=%s",
                compra_id,
                status or "PENDIENTE",
            )
    except Exception:
        logger.exception("No se pudo procesar el hook de sujeto excluido para compra %s", compra_id)
