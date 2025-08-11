import os
import requests
from msal import ConfidentialClientApplication

CLIENT_ID = os.environ["AZURE_CLIENT_ID"]
CLIENT_SECRET = os.environ["AZURE_CLIENT_SECRET"]
TENANT_ID = os.environ["AZURE_TENANT_ID"]
SENDER = os.environ.get("AZURE_SENDER_EMAIL")

app = ConfidentialClientApplication(
    client_id=CLIENT_ID,
    client_credential=CLIENT_SECRET,
    authority=f"https://login.microsoftonline.com/{TENANT_ID}"
)

token_result = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
access_token = token_result.get("access_token")
if not access_token:
    raise RuntimeError(f"No se pudo obtener token: {token_result.get('error_description')}")

message = {
    "message": {
        "subject": "Hola desde OAuth",
        "body": {
            "contentType": "Text",
            "content": "¡Mensaje enviado con autenticación moderna!"
        },
        "toRecipients": [
            {"emailAddress": {"address": os.environ.get("AZURE_TEST_RECIPIENT")}}
        ]
    }
}

send_url = f"https://graph.microsoft.com/v1.0/users/{SENDER}/sendMail"
headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
response = requests.post(send_url, headers=headers, json=message)

if response.status_code == 202:
    print("Correo enviado correctamente.")
else:
    print("Error al enviar correo:", response.status_code, response.text)
