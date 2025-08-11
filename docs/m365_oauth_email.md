# Envío de correo con Microsoft 365 y OAuth 2.0

Guía rápida para reemplazar la autenticación SMTP básica por OAuth 2.0 usando
Microsoft Graph.

## 1. Registrar la aplicación en Azure Active Directory

1. Ingresa al [portal de Azure](https://portal.azure.com/).
2. Dirígete a **Azure Active Directory → App registrations** y selecciona
   **New registration**.
3. Asigna un nombre a la aplicación y registra el redirect URI si usarás el
   flujo **Authorization Code** (por ejemplo `http://localhost:8000/callback`).
4. Tras crearla copia los valores de **Application (client) ID** y
   **Directory (tenant) ID**.

### Generar un `client_secret`

1. Dentro del registro de la aplicación ve a **Certificates & secrets**.
2. Crea un nuevo **Client secret** y guarda su valor; se mostrará solo una vez.

### Otorgar permisos

1. En **API permissions** elige **Add a permission → Microsoft Graph**.
2. Selecciona **Application permissions** y marca `Mail.Send`.
3. Haz clic en **Grant admin consent** para aplicar el permiso a todo el tenant.

## 2. Obtener un token de acceso

### Flujo *Client Credentials*

El script [`send_mail.py`](../send_mail.py) usa este flujo. Define las
variables de entorno requeridas y ejecuta:

```bash
export AZURE_TENANT_ID=<tu_tenant>
export AZURE_CLIENT_ID=<tu_app_id>
export AZURE_CLIENT_SECRET=<tu_client_secret>
export AZURE_SENDER_EMAIL=<buzon@dominio.com>
export AZURE_TEST_RECIPIENT=<destinatario@dominio.com>
python send_mail.py
```

MSAL almacena en caché el token y lo renueva automáticamente cuando expira
(`acquire_token_silent`); no se maneja un *refresh token* explícito en este
flujo.

### Flujo *Authorization Code* (opcional)

Para enviar correos en nombre de un usuario interactivo, registra el redirect
URI y usa `Msal.PublicClientApplication` o una biblioteca compatible para
obtener el `authorization_code`. Tras el primer inicio de sesión MSAL guardará
un *refresh token* y `acquire_token_silent` permitirá renovar el `access_token`
sin intervención del usuario.

## 3. Manejo de errores comunes

- **401/invalid_grant**: verifica `client_id`, `client_secret` y `tenant_id`.
- **403/Insufficient privileges**: la aplicación no tiene el permiso `Mail.Send`
  o no se otorgó **admin consent**.
- **429/503**: reintenta luego de unos segundos respetando los encabezados
  `Retry-After` devueltos por el servicio.

## 4. Verificar el envío

1. Ejecuta `send_mail.py`.
2. El script imprimirá `Correo enviado correctamente.` si Microsoft Graph
   devuelve un código `202 Accepted`.
3. Revisa el buzón del destinatario para confirmar la recepción.

Esta guía se basa en el uso de Microsoft Graph; también es posible autenticar
contra el servidor SMTP de Microsoft 365 usando OAuth 2.0, pero se recomienda
preferir Graph para nuevas integraciones.

