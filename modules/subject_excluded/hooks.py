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
