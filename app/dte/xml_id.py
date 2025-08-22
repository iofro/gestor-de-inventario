"""Build XML identification snippet for DTE envelopes."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Dict
from uuid import uuid4


def build_dte_id_xml(envelope: Dict, mutate: bool = True) -> str:
    """Return an identification XML snippet for ``envelope``.

    If ``codigoGeneracion`` is missing a UUIDv4 is generated and injected
    (uppercased).  Only non-empty values are emitted and the root tag is
    ``DTEId`` as required by the spec.
    """

    ident = envelope.setdefault("identificacion", {}) if mutate else envelope.get("identificacion", {})

    cg = ident.get("codigoGeneracion")
    if not cg:
        cg = str(uuid4()).upper()
        ident["codigoGeneracion"] = cg
    else:
        ident["codigoGeneracion"] = str(cg).upper()

    root = ET.Element("DTEId")

    def add(tag: str, val):
        if val not in (None, ""):
            ET.SubElement(root, tag).text = str(val)

    add("TipoDte", ident.get("tipoDte"))
    add("CodigoGeneracion", ident.get("codigoGeneracion"))
    add("NumeroControl", ident.get("numeroControl"))
    add("Ambiente", ident.get("ambiente"))
    add("FechaEmision", ident.get("fecEmi"))
    add("HoraEmision", ident.get("horEmi"))

    xml_bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    return xml_bytes.decode("utf-8")

