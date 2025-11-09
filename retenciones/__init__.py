# Retención DTE bootstrap module
#
# This module is intentionally tiny and isolated.  All VAT retention (DTE 07)
# specific logic should live here so that deleting this package removes every
# trace of the feature without touching the rest of the codebase.
#
# The goal is to keep a clear starting point for implementing the future
# retención workflow while already exposing the shape required by the official
# schema located at: svfe-json-schemas/fe-cr-v1.json
#
# Nothing here performs validation, persistence or integrations.  It only
# exposes the minimum data containers and helpers that upcoming work can build
# upon.  Keep it simple and keep extensive logic elsewhere until the design is
# agreed on.

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# Reference to the JSON schema that describes Comprobante de Retención
# Electrónica (DTE tipo 07).  Future changes should stay in sync with that file.
SCHEMA_REFERENCE = "svfe-json-schemas/fe-cr-v1.json"


@dataclass
class RetencionDTE07Outline:
    """Minimal container for the main sections of a retention DTE draft.

    Each attribute mirrors a top-level property of the JSON schema.  The idea
    is to grow this structure gradually with proper types, validation rules and
    business logic.  For now we only need a predictable place to stash data.
    """

    identificacion: Dict[str, Any] = field(default_factory=dict)
    emisor: Dict[str, Any] = field(default_factory=dict)
    receptor: Dict[str, Any] = field(default_factory=dict)
    cuerpo_documento: List[Dict[str, Any]] = field(default_factory=list)
    resumen: Dict[str, Any] = field(default_factory=dict)
    extension: Optional[Dict[str, Any]] = None
    apendice: List[Dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        """Return the raw dictionary representation expected by the schema.

        This method does not validate or transform data.  It simply exposes the
        internal structure so other parts of the system can inspect or serialize
        it once the real implementation is ready.
        """

        return {
            "identificacion": self.identificacion,
            "emisor": self.emisor,
            "receptor": self.receptor,
            "cuerpoDocumento": self.cuerpo_documento,
            "resumen": self.resumen,
            "extension": self.extension,
            "apendice": self.apendice,
        }


def create_retencion_borrador() -> RetencionDTE07Outline:
    """Create a skeleton retention document populated with placeholder values.

    Use this factory when you need a predictable structure to start wiring UI
    forms, mocks or tests.  Every key that the schema marks as required is
    present, but the values are deliberately simple so future work can replace
    them with real data and validation rules.
    """

    outline = RetencionDTE07Outline()

    outline.identificacion.update(
        {
            "version": 1,
            "ambiente": "00",  # TODO: derivar de la configuración del contribuyente.
            "tipoDte": "07",
            "numeroControl": "<pendiente>",  # TODO: generar según reglas MH.
            "codigoGeneracion": "<uuid-pendiente>",
            "tipoModelo": 1,
            "tipoOperacion": 1,
            "tipoContingencia": None,
            "motivoContin": None,
            "fecEmi": "<yyyy-mm-dd>",
            "horEmi": "<hh:mm:ss>",
            "tipoMoneda": "USD",
        }
    )

    outline.emisor.update(
        {
            "nit": "",
            "nrc": "",
            "nombre": "",
            "codActividad": "",
            "descActividad": "",
            "nombreComercial": None,
            "tipoEstablecimiento": "",
            "direccion": {
                "departamento": "",
                "municipio": "",
                "complemento": "",
            },
            "telefono": None,
            "codigoMH": None,
            "codigo": None,
            "puntoVentaMH": None,
            "puntoVenta": None,
            "correo": "",
        }
    )

    outline.receptor.update(
        {
            "tipoDocumento": "",
            "numDocumento": "",
            "nrc": None,
            "nombre": "",
            "codActividad": "",
            "descActividad": "",
            "nombreComercial": None,
            "direccion": {
                "departamento": "",
                "municipio": "",
                "complemento": "",
            },
            "telefono": None,
            "correo": "",
        }
    )

    outline.cuerpo_documento.append(
        {
            "numItem": 1,
            "tipoDte": "01",
            "tipoDoc": 1,
            "numDocumento": "",
            "fechaEmision": "<yyyy-mm-dd>",
            "montoSujetoGrav": 0.0,
            "codigoRetencionMH": "22",
            "ivaRetenido": 0.0,
            "descripcion": "",
            # "codGeneracion" quedará pendiente hasta conocer la fuente del documento.
        }
    )

    outline.resumen.update(
        {
            "totalSujetoRetencion": 0.0,
            "totalIVAretenido": 0.0,
            "totalIVAretenidoLetras": "",
        }
    )

    # extension y apéndice se dejan vacíos; la schema permite null/arreglos.

    return outline


__all__ = [
    "SCHEMA_REFERENCE",
    "RetencionDTE07Outline",
    "create_retencion_borrador",
]
