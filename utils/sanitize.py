from __future__ import annotations

"""Utilities for sanitizing document numbers."""


def limpiar_doc(s: str | None) -> str:
    """Return ``s`` without hyphens or spaces.

    Parameters
    ----------
    s: str | None
        Input document identifier.
    """
    if not s:
        return ""
    return "".join(ch for ch in str(s) if ch.isalnum())


def solo_digitos(s: str | None) -> str:
    """Return only the digit characters from ``s``.

    Parameters
    ----------
    s: str | None
        Input value possibly containing non-digit characters.
    """
    if not s:
        return ""
    return "".join(ch for ch in str(s) if ch.isdigit())


def limpiar_documentos(data: dict | None) -> None:
    """Sanitize document numbers inside ``data`` in-place."""
    if not isinstance(data, dict):
        return
    for key, value in list(data.items()):
        if isinstance(value, dict):
            limpiar_documentos(value)
        elif isinstance(value, str):
            kl = key.lower()
            if kl in {"nit", "nrc", "numdocumento", "dui", "pasaporte"} or "doc" in kl:
                if kl not in {"numerocontrol", "codigogeneracion"} and key != "numeroDocumento":
                    if kl in {"nrc", "numdocumento"}:
                        data[key] = solo_digitos(value)
                    else:
                        data[key] = limpiar_doc(value)
