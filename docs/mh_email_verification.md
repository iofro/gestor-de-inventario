# Verificación del flujo MH → correo

## A. Preparación
- **A1. Datos del cliente**: El envío de factura/ticket verifica que el cliente tenga email antes de continuar y cancela con advertencia si falta. 【facturacion_tab.py†L4336-L4355】【facturacion_tab.py†L5561-L5576】
- **A2. Credenciales SMTP**: Antes de enviar correo se cargan valores desde `DATOS_NEGOCIO_PATH` y se valida que servidor, puerto, usuario y contraseña existan; si no, se aborta. 【facturacion_tab.py†L4441-L4460】【facturacion_tab.py†L5593-L5606】
- **A3. Token MH**: Las respuestas 401/403 disparan mensaje de token desactualizado y detienen el flujo. 【facturacion_tab.py†L3335-L3347】【facturacion_tab.py†L3402-L3408】
- **A4. Ubicación de archivos**: Tras regenerar, se reutiliza la ruta canónica del PDF carta y su JSON compañero (`<ruta>.pdf` + `<ruta>.json`). El email adjunta precisamente esos paths. 【facturacion_tab.py†L4319-L4350】【facturacion_tab.py†L4469-L4487】

## B. Flujo feliz
- **B1. Seleccionar venta**: Al elegir una venta válida el botón permanece activo; omisiones muestran advertencia. 【facturacion_tab.py†L3267-L3290】
- **B2. Opciones**: Se consulta `SendOptionsDialog` y, si se marca Hacienda, el log imprime `UI: CALL_ENVIAR_DOCUMENTO` antes del correo. 【facturacion_tab.py†L3309-L3334】【facturacion_tab.py†L3389-L3393】
- **B3. Respuesta aceptada**: Solo si `estado` = "aceptado" y hay sello se marca `mh_success` y se guarda la respuesta. 【facturacion_tab.py†L3334-L3356】【facturacion_tab.py†L3393-L3403】
- **B4. Persistencia y regeneración**: `_update_invoice_assets_after_mh` guarda código, número, ambiente y sello en la venta antes de regenerar el PDF; luego sincroniza el JSON. 【facturacion_tab.py†L4295-L4340】
- **B5. QR actualizado**: `generate_invoice_pdf` lee los valores actualizados para generar QR y propaga el sello en el JSON. 【utils/doc_generation.py†L322-L410】【utils/doc_generation.py†L433-L452】
- **B6. Adjuntos coherentes**: Antes de enviar, `_send_invoice_email` valida que el JSON contenga el código y sello esperados, regenerando una vez si no coinciden y abortando si persiste el problema. Los adjuntos son exactamente ese PDF y JSON. 【facturacion_tab.py†L4358-L4460】【facturacion_tab.py†L4469-L4524】
- **B7. Envío por correo**: Tras validación exitosa se arma el hilo de envío con esos adjuntos. 【facturacion_tab.py†L4469-L4498】

## C. Estados no aceptados
- **C1. Transmitido/Recibido/Procesado**: Se muestran mensajes informativos y `mh_success` sigue en `False`, por lo que el correo se bloquea cuando se pidió envío a Hacienda. 【facturacion_tab.py†L3361-L3387】【facturacion_tab.py†L3413-L3431】
- **C2. Rechazado**: Se muestra mensaje crítico y no se envía correo. 【facturacion_tab.py†L3387-L3412】【facturacion_tab.py†L3431-L3450】

## D. Orphan / Ticket
- **D1. Orphan**: Se reutiliza la misma verificación de estado y sello antes de permitir `_send_orphan_email`; en caso de rechazo o pendientes, `mh_success` evita el correo. 【facturacion_tab.py†L3318-L3379】【facturacion_tab.py†L3413-L3431】
- **D2. Ticket**: El flujo marca `mh_success` y `_send_ticket_email` aplica las mismas validaciones de email y adjuntos del ticket. 【facturacion_tab.py†L3431-L3453】【facturacion_tab.py†L5556-L5606】

## E. Integridad de artefactos
- **E1. Un solo PDF**: La regeneración reutiliza `_generate_invoice_pdf` sin cambiar el nombre, por lo que solo se actualiza `mtime`. 【facturacion_tab.py†L4321-L4330】【facturacion_tab.py†L4358-L4378】
- **E2. Coherencia PDF↔JSON**: La verificación posterior obliga a que JSON y PDF correspondan al mismo código/sello antes de enviar. 【facturacion_tab.py†L4358-L4440】

## F. Robustez y mensajes
- **F1. Token vencido**: Mensaje y salida sin correo. 【facturacion_tab.py†L3335-L3347】【facturacion_tab.py†L3402-L3408】
- **F2. Sin Internet**: Detecta el detalle "Sin conexión a Internet" y muestra mensaje crítico. 【facturacion_tab.py†L3361-L3370】
- **F3. Cliente sin email**: Se aborta con advertencia. 【facturacion_tab.py†L4336-L4355】

## G. Consistencias adicionales
- **G1. Normalización de sello**: Se acepta `sello`, `selloRecibido` o `selloRecepcion` y se normaliza antes de validar. 【facturacion_tab.py†L3334-L3356】【facturacion_tab.py†L4381-L4395】
- **G2. Mayúsculas del código**: El código se normaliza a mayúsculas al persistir y al validar el JSON. 【facturacion_tab.py†L4300-L4340】【facturacion_tab.py†L4398-L4414】
- **G3. Identificación faltante**: `_ensure_invoice_json_metadata` crea/actualiza `identificacion` con el código y agrega `selloRecibido`, incluso si faltaban. 【facturacion_tab.py†L4499-L4541】
