"""Base envelopes for DTE generation.

This module defines skeleton structures for different DTE documents.
For each supported tipo DTE the corresponding envelope sets
``identificacion.tipoDte`` to the fixed value dictated by the
specification while leaving the rest of fields initialised to ``None``.
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


# Base envelope for Nota de Remisión (NR v3)
NR_BASE: dict = {
    "identificacion": {
        "version": None,
        "ambiente": None,
        "tipoDte": "04",
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


__all__ = ["ND_BASE", "NR_BASE"]
