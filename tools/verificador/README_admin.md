# Verificador de licencias de Vertex

El verificador es una herramienta administrativa para generar y mantener licencias firmadas para los sistemas de inventario Vertex. **No forma parte del instalador del sistema de inventario ni debe distribuirse a los clientes.**

## Operación general

1. Configure la carpeta compartida SMB que contendrá las licencias firmadas (`licenses/`) y las solicitudes de alta (`requests/`).
2. Ajuste las rutas en `admin_config.json` desde la aplicación (`Configuración...`).
3. Genere el par de claves Ed25519 con el botón **Generar claves...**. La clave pública se comparte con los clientes; la privada nunca debe salir del equipo del administrador.
4. Use **Actualizar** para cargar las solicitudes y licencias existentes, apruebe nuevas solicitudes y cambie estados según sea necesario. Cada cambio reescribe el archivo JSON con una firma Ed25519 del payload canónico.

### Carpeta de claves

La carpeta `tools/verificador/keys/` contiene la clave privada y pública del verificador. Debe mantenerse fuera del control de versiones por seguridad. Añada esta ruta a su `.git/info/exclude` o a las exclusiones locales de su cliente Git. No modifique `.gitignore` global del repositorio.

## Formato de archivos

Los archivos en `licenses/{device_id}.json` incluyen el payload canónico:

```json
{
  "device_id": "...",
  "status": "ACTIVE|BLOCKED|EXPIRED|TRIAL|GRACE",
  "expires_at": "ISO8601|null",
  "grace_until": "ISO8601|null",
  "issued_at": "ISO8601"
}
```

La aplicación firma el payload canonizado con `json.dumps(payload, separators=(",", ":"), sort_keys=True)` y guarda la firma como `signature` codificada en Base64. Los metadatos adicionales (`alias`, `notes`, etc.) se almacenan junto al payload pero no forman parte de la firma.

## Modos de conexión

* **Carpeta compartida**: accesos SMB configurables. Es el modo actualmente implementado.
* **HTTP local**: reservado para una futura API; la interfaz permite seleccionarlo, pero aún no hay backend.

## Exclusión de builds

Los scripts de PyInstaller e Inno Setup del inventario excluyen `tools/verificador/**` para evitar que esta herramienta aparezca en los paquetes distribuidos a clientes.

