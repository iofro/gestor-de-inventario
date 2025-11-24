Comprobante de Retención (CR-07)
================================

Este módulo genera, valida, firma y transmite Comprobantes de Retención usando
el catálogo `docs/catalogos_retencion.xlsx` y los esquemas oficiales
`svfe-json-schemas/fe-cr-v1.json` y `fe-ccf-v3.json`. Los CR se almacenan en la
tabla `retenciones_cr` enlazados a la venta/DTE de origen (solo facturas tipo
03). Cada DTE de crédito fiscal puede generar **un** CR; un segundo intento
arroja un error controlado.

Flujo básico
------------

1. **Generar y persistir** el CR desde una venta confirmada (`ventas.id`):

   ```bash
   python tools/build_cr.py --venta-id 123 --tipo-dte 03 --output out/cr-123.json
   ```

   El comando crea el payload con `CR.BUILD`, lo valida (`CR.VALIDATE`) y lo
   guarda en `retenciones_cr.payload_json`. También emite `CR.STORE` con los
   totales base/1%.

2. **Firmar** el CR con el firmador configurado (guarda el JWS en la base):

   ```bash
   python tools/build_cr.py --venta-id 123 --tipo-dte 03 --sign --sign-output out/cr-123.jws
   ```

   El JWS también queda persistido en `retenciones_cr.jws` para futuros
   reenvíos.

3. **Transmitir** a Hacienda (firmará automáticamente si hace falta):

   ```bash
   python tools/build_cr.py --venta-id 123 --tipo-dte 03 --send
   ```

   El envío produce los logs `CR.SEND`, `RETENCION.SEND` y `CR.RESP`, y guarda
   el resultado normalizado (estado, detalle, sello) en la tabla. El flujo usa
   la misma configuración (`dte_api.url`, tokens, certificados) que los DTE
   tradicionales.

Notas
-----

- Asegúrate de tener `docs/catalogos_retencion.xlsx` actualizado.
- El catálogo de retenciones se consulta en caliente para validar los códigos
  CAT-001/002/003/004/006/009/022 usados en el CR.
- Los CR se almacenan en `RETENCIONES_DIR` cuando se especifica `--output`. El
  envío siempre persiste la respuesta del MH aunque falle.
