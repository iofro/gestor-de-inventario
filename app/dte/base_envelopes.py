"""Base envelopes for DTE generation.

This module defines skeleton structures for different DTE documents.
For the debit note ("Nota de Débito") all fields are initialised to
``None`` except for ``identificacion.tipoDte`` which is fixed to ``"06"``
according to the official specification.
"""

from __future__ import annotations

# Base envelope for Nota de Débito (ND v3)
ND_BASE: dict = {
    "identificacion": {
        "version": None,
        "ambiente": None,
        "tipoDte": "06",
        "numeroControl": None,
        "codigoGeneracion": None,
        "tipoModelo": None,
        "tipoOperacion": None,
        "tipoContingencia": None,
        "motivoContin": None,
        "fecEmi": None,
        "horEmi": None,
        "tipoMoneda": None,
    },
    "documentoRelacionado": None,
    "emisor": None,
    "receptor": None,
    "ventaTercero": None,
    "cuerpoDocumento": None,
    "resumen": None,
    "extension": None,
    "apendice": None,
}

__all__ = ["ND_BASE"]
