"""Base envelopes for DTE documents.

Currently only ``NC_BASE`` is defined for Nota de Crédito
(identificador 05).  All fields are initialised to ``None`` except for
``identificacion.tipoDte`` which is set to "05" as required by the
specification.
"""
from __future__ import annotations

from copy import deepcopy

# Nota de Crédito (05) base envelope.  The structure mirrors the schema for
# the NCE but with ``None`` for every value so that callers can ``deepcopy``
# this constant and populate the required fields dynamically.
NC_BASE: dict = {
    "identificacion": {
        "version": None,
        "ambiente": None,
        "tipoDte": "05",
        "codigoGeneracion": None,
        "numeroControl": None,
        "fecEmi": None,
        "horEmi": None,
        "tipoMoneda": None,
        "tipoContingencia": None,
        "motivoContin": None,
        "tipoModelo": None,
        "tipoOperacion": None,
    },
    "documentoRelacionado": None,
    "emisor": {
        "nit": None,
        "nrc": None,
        "nombre": None,
        "codActividad": None,
        "descActividad": None,
        "nombreComercial": None,
        "tipoEstablecimiento": None,
        "direccion": {
            "departamento": None,
            "municipio": None,
            "complemento": None,
        },
        "telefono": None,
        "correo": None,
    },
    "receptor": {
        "nit": None,
        "nrc": None,
        "nombre": None,
        "codActividad": None,
        "descActividad": None,
        "nombreComercial": None,
        "direccion": {
            "departamento": None,
            "municipio": None,
            "complemento": None,
        },
        "telefono": None,
        "correo": None,
    },
    "ventaTercero": None,
    "cuerpoDocumento": None,
    "resumen": None,
    "extension": None,
    "apendice": None,
}


def clone_nc_base() -> dict:
    """Return a deep copy of :data:`NC_BASE`.

    This helper mirrors the behaviour described in the user story where a
    fresh envelope is created for each button press by cloning the base
    structure.
    """

    return deepcopy(NC_BASE)
