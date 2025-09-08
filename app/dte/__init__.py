"""Convenience imports for DTE utilities used in tests."""

from .base_envelopes import ND_BASE, NR_BASE
from .identifiers import ND_CONTROL_REGEX, NR_CONTROL_REGEX, ensure_numero_control
from .validation import validate_dte
from .xml_id import build_dte_id_xml
from .signing import sign_dte, LocalRS256Signer

__all__ = [
    "ND_BASE",
    "NR_BASE",
    "ND_CONTROL_REGEX",
    "NR_CONTROL_REGEX",
    "ensure_numero_control",
    "validate_dte",
    "build_dte_id_xml",
    "sign_dte",
    "LocalRS256Signer",
]
