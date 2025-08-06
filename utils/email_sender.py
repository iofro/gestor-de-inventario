from PyQt5.QtCore import QThread, pyqtSignal
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import os


class EmailSender(QThread):
    finished = pyqtSignal(bool, str)

    def __init__(self, server, port, user, password, to_addr, subject, body, attachments):
        super().__init__()
        self.server = server
        self.port = port
        self.user = user
        self.password = password
        self.to_addr = to_addr
        self.subject = subject
        self.body = body
        if isinstance(attachments, str):
            self.attachments = [attachments]
        else:
            self.attachments = attachments or []

    def run(self):
        try:
            msg = MIMEMultipart()
            msg["From"] = self.user
            msg["To"] = self.to_addr
            msg["Subject"] = self.subject
            msg.attach(MIMEText(self.body or "", "plain"))

            for path in self.attachments:
                with open(path, "rb") as f:
                    part = MIMEBase("application", "octet-stream")
                    part.set_payload(f.read())
                encoders.encode_base64(part)
                part.add_header(
                    "Content-Disposition",
                    f'attachment; filename="{os.path.basename(path)}"',
                )
                msg.attach(part)

            smtp = smtplib.SMTP(self.server, int(self.port))
            smtp.starttls()
            smtp.login(self.user, self.password)
            smtp.send_message(msg)
            smtp.quit()
            self.finished.emit(True, "Correo enviado correctamente")
        except Exception as e:
            self.finished.emit(False, str(e))
