import logging


logger = logging.getLogger(__name__)


def generate_subject_excluded_dte_stub(compra_id: int) -> None:
    """Stub para DTE tipo 14 de compras a sujetos excluidos."""

    try:
        print("TODO: implementar DTE tipo 14 para compra", compra_id)
    except Exception:
        logger.exception("No se pudo ejecutar el stub de DTE sujeto excluido")
