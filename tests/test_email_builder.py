import os

from utils.email_builder import build_email


def test_build_email_returns_components(tmp_path):
    pdf = tmp_path / "doc.pdf"
    json_file = tmp_path / "doc.json"
    pdf.write_bytes(b"%PDF")
    json_file.write_text("{}", encoding="utf-8")

    meta = {"subject": " Subj ", "body": "Cuerpo"}
    email = build_email("to@example.com", meta, str(pdf), str(json_file))

    assert email["to"] == "to@example.com"
    assert email["subject"] == "Subj"
    assert email["attachments"] == [str(pdf), str(json_file)]
    assert "Cuerpo" in email["body"]
    assert "Se adjuntan" in email["body"]
