from PyQt5.QtCore import QThread, pyqtSignal
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import os
import base64


class EmailSender(QThread):
    finished = pyqtSignal(bool, str)

    def __init__(
        self,
        server,
        port,
        user,
        password,
        to_addr,
        subject,
        body,
        attachments,
        oauth_token=None,
    ):
        super().__init__()
        self.server = server
        self.port = port
        self.user = user
        self.password = password
        self.to_addr = to_addr
        self.subject = subject
        self.body = body
        self.oauth_token = oauth_token
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
            if self.oauth_token:
                auth_str = f"user={self.user}\1auth=Bearer {self.oauth_token}\1\1"
                b64 = base64.b64encode(auth_str.encode()).decode()
                smtp.docmd("AUTH", "XOAUTH2 " + b64)
            else:
                smtp.login(self.user, self.password)
            smtp.send_message(msg)
            smtp.quit()
            self.finished.emit(True, "Correo enviado correctamente")
        except smtplib.SMTPAuthenticationError as e:
            error_msg = e.smtp_error.decode() if isinstance(e.smtp_error, bytes) else str(e.smtp_error)
            self.finished.emit(False, f"Error de autenticación: {error_msg}")
        except Exception as e:
            self.finished.emit(False, str(e))
