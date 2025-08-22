"""Generate auxiliary XML identifiers for DTE documents."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Dict, Any


def build_dte_id_xml(envelope: Dict[str, Any]) -> str:
    """Return an XML string containing identification fields.

    The XML includes ``TipoDte``, ``CodigoGeneracion``, ``NumeroControl``,
    ``Ambiente``, ``FechaEmision`` and ``HoraEmision`` as required by the
    signing service.
    """

    ident = envelope.get("identificacion", {})
    root = ET.Element("Identificacion")
    ET.SubElement(root, "TipoDte").text = ident.get("tipoDte") or ""
    ET.SubElement(root, "CodigoGeneracion").text = ident.get("codigoGeneracion") or ""
    ET.SubElement(root, "NumeroControl").text = ident.get("numeroControl") or ""
    ET.SubElement(root, "Ambiente").text = ident.get("ambiente") or ""
    ET.SubElement(root, "FechaEmision").text = ident.get("fecEmi") or ""
    ET.SubElement(root, "HoraEmision").text = ident.get("horEmi") or ""
    return ET.tostring(root, encoding="unicode")


__all__ = ["build_dte_id_xml"]
