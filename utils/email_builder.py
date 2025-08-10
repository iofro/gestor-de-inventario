"""Helper to build email data for sending DTE documents."""

from typing import Dict, List


def build_email(to: str, dte_meta: Dict, pdf_path: str, json_path: str) -> Dict[str, object]:
    """Return a simple dictionary with the email components.

    Parameters
    ----------
    to: str
        Recipient email address.
    dte_meta: Dict
        Metadata containing at least ``subject`` and ``body`` keys. Additional
        values are ignored. The subject is stripped of surrounding whitespace.
    pdf_path: str
        Path to the PDF representation of the document.
    json_path: str
        Path to the signed JSON document.

    Returns
    -------
    dict
        Dictionary with ``to``, ``subject``, ``body`` and ``attachments`` keys.
    """

    subject = (dte_meta or {}).get("subject", "").strip()
    body = (dte_meta or {}).get("body", "")
    body += (
        "\n\nSe adjuntan la representación gráfica en PDF y el documento firmado en formato JSON."
    )
    attachments: List[str] = []
    for path in (pdf_path, json_path):
        if path:
            attachments.append(path)
    return {"to": to, "subject": subject, "body": body, "attachments": attachments}
