"""Ejemplo de envío de correo mediante Microsoft 365 usando OAuth 2.0.

Este script reemplaza la autenticación básica (usuario/contraseña) por un flujo
de *client credentials* y el endpoint ``sendMail`` de Microsoft Graph. Para
utilizarlo define las siguientes variables de entorno:

* ``AZURE_CLIENT_ID`` – ID de la aplicación registrada en Azure AD.
* ``AZURE_CLIENT_SECRET`` – secreto de cliente generado en Azure AD.
* ``AZURE_TENANT_ID`` – identificador del tenant donde se registró la app.
* ``AZURE_SENDER_EMAIL`` – dirección del buzón que enviará el correo.
* ``AZURE_TEST_RECIPIENT`` – destinatario de prueba.

El permiso ``Mail.Send`` (Application) debe concederse a la aplicación y
contar con *admin consent*.
"""

import os
import re
import requests
from msal import ConfidentialClientApplication, MsalServiceError

CLIENT_ID = os.environ["AZURE_CLIENT_ID"]
CLIENT_SECRET = os.environ["AZURE_CLIENT_SECRET"]
TENANT_ID = os.environ["AZURE_TENANT_ID"]
SENDER = os.environ["AZURE_SENDER_EMAIL"]
RECIPIENT = os.environ["AZURE_TEST_RECIPIENT"]

SCOPE = ["https://graph.microsoft.com/.default"]

# Inicializa el cliente confidencial de MSAL. Internamente manejará el caché
# de tokens y renovará el access token cuando caduque.
app = ConfidentialClientApplication(
    client_id=CLIENT_ID,
    client_credential=CLIENT_SECRET,
    authority=f"https://login.microsoftonline.com/{TENANT_ID}",
)


def get_access_token() -> str:
    """Obtiene un token de acceso válido.

    Primero intenta recuperar un token en caché (``acquire_token_silent``). Si no
    existe o ya expiró, solicita uno nuevo. Para el flujo de *client
    credentials* no se utilizan tokens de actualización; simplemente se genera
    un nuevo access token cuando sea necesario.
    """

    result = app.acquire_token_silent(SCOPE, account=None)
    if not result:
        try:
            result = app.acquire_token_for_client(scopes=SCOPE)
        except MsalServiceError as exc:
            raise RuntimeError(f"Error al solicitar token a Azure AD: {exc}") from exc

    token = result.get("access_token")
    if not token:
        raise RuntimeError(f"No se pudo obtener token: {result.get('error_description')}")
    return token


def send_mail(subject: str, content: str, recipient: str) -> None:
    """Envía un correo utilizando Microsoft Graph.

    Args:
        subject: Asunto del correo.
        content: Cuerpo del mensaje en texto plano.
        recipient: Dirección del destinatario.

    Lanza ``RuntimeError`` si la API devuelve un código distinto de 202.
    """

    access_token = get_access_token()
    message = {
        "message": {
            "subject": subject,
            "body": {"contentType": "Text", "content": content},
            "toRecipients": [{"emailAddress": {"address": recipient}}],
        }
    }

    send_url = f"https://graph.microsoft.com/v1.0/users/{SENDER}/sendMail"
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    print(repr(headers["Authorization"]))
    assert re.fullmatch(r"Bearer [^\s]+", headers["Authorization"]), "Authorization header malformado"
    response = requests.post(send_url, headers=headers, json=message)
    if response.status_code != 202:
        raise RuntimeError(f"Error al enviar correo: {response.status_code} {response.text}")


if __name__ == "__main__":
    try:
        send_mail(
            subject="Hola desde OAuth",
            content="¡Mensaje enviado con autenticación moderna!",
            recipient=RECIPIENT,
        )
        print("Correo enviado correctamente.")
    except Exception as err:  # pragma: no cover - manejo simple para este ejemplo
        # Si la respuesta es 403 verifica que la aplicación tenga el permiso
        # Mail.Send y que se haya otorgado el consentimiento de administrador.
        print(f"Error al enviar correo: {err}")

