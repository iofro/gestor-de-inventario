import os
import smtplib

import pytest
from PyQt5.QtWidgets import QApplication

from utils.email_sender import EmailSender


@pytest.fixture(scope="module")
def qt_app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    return app


def _create_files(tmp_path):
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    json_file = tmp_path / "doc.json"
    json_file.write_text("{}", encoding="utf-8")
    return pdf, json_file


def test_envio_exitoso(tmp_path, monkeypatch, qt_app):
    pdf, json_file = _create_files(tmp_path)

    captured = {}

    class FakeSMTP:
        def __init__(self, server, port):
            captured["init"] = (server, port)

        def starttls(self):
            captured["starttls"] = True

        def login(self, user, password):
            captured["login"] = (user, password)

        def send_message(self, msg):
            captured["message"] = msg

        def quit(self):
            captured["quit"] = True

    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)

    sender = EmailSender(
        "smtp.example.com",
        25,
        "user@example.com",
        "pw",
        "to@example.com",
        "Asunto",
        "Cuerpo",
        [str(pdf), str(json_file)],
    )

    results = []
    sender.finished.connect(lambda ok, msg: results.append((ok, msg)))

    sender.run()

    msg = captured["message"]
    assert msg["Subject"] == "Asunto"
    assert msg["To"] == "to@example.com"
    text_part = next(p for p in msg.walk() if p.get_content_type() == "text/plain")
    assert text_part.get_payload(decode=True).decode() == "Cuerpo"

    filenames = []
    for part in msg.walk():
        cd = part.get("Content-Disposition")
        if cd and cd.startswith("attachment"):
            filenames.append(part.get_filename())
    assert sorted(filenames) == sorted([pdf.name, json_file.name])

    assert results == [(True, "Correo enviado correctamente")]


def test_envio_error_smtp(tmp_path, monkeypatch, qt_app):
    pdf, json_file = _create_files(tmp_path)

    class ErrorSMTP:
        def __init__(self, server, port):
            pass

        def starttls(self):
            pass

        def login(self, user, password):
            pass

        def send_message(self, msg):
            raise smtplib.SMTPException("fallo")

        def quit(self):
            pass

    monkeypatch.setattr(smtplib, "SMTP", ErrorSMTP)

    sender = EmailSender(
        "smtp.example.com",
        25,
        "user@example.com",
        "pw",
        "to@example.com",
        "Asunto",
        "Cuerpo",
        [str(pdf), str(json_file)],
    )

    results = []
    sender.finished.connect(lambda ok, msg: results.append((ok, msg)))

    sender.run()

    assert results and results[0][0] is False
    assert "fallo" in results[0][1]
