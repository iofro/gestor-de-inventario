# Reporte de diagnóstico de certificados

- Fecha y hora: 2025-10-02T03:31:48.257734
- Sistema operativo: Linux-6.12.13-x86_64-with-glibc2.39
- CERT dirs efectivos: /tmp/pytest-of-root/pytest-0/test_firmador_803_diagnostico_0/certs, /tmp/pytest-of-root/pytest-0/test_firmador_803_diagnostico_1/certs, /tmp/pytest-of-root/pytest-0/test_firmador_803_diagnostico_2/certs, /tmp/pytest-of-root/pytest-0/test_firmador_803_diagnostico_3/certs, /tmp/pytest-of-root/pytest-0/test_firmador_803_diagnostico_4/certs, /tmp/pytest-of-root/pytest-0/test_firmador_803_diagnostico_5/certs
- FIRMADOR_CERT_DIR observados: /tmp/pytest-of-root/pytest-0/test_firmador_803_diagnostico_0/certs, /tmp/pytest-of-root/pytest-0/test_firmador_803_diagnostico_1/certs, /tmp/pytest-of-root/pytest-0/test_firmador_803_diagnostico_2/certs, /tmp/pytest-of-root/pytest-0/test_firmador_803_diagnostico_3/signer_dir, /tmp/pytest-of-root/pytest-0/test_firmador_803_diagnostico_4/certs, /tmp/pytest-of-root/pytest-0/test_firmador_803_diagnostico_5/certs
- CERT_UPLOAD_DIR (env): /tmp/pytest-of-root/pytest-0/test_firmador_803_diagnostico_0/certs, /tmp/pytest-of-root/pytest-0/test_firmador_803_diagnostico_1/certs, /tmp/pytest-of-root/pytest-0/test_firmador_803_diagnostico_2/certs, /tmp/pytest-of-root/pytest-0/test_firmador_803_diagnostico_3/certs, /tmp/pytest-of-root/pytest-0/test_firmador_803_diagnostico_4/certs, /tmp/pytest-of-root/pytest-0/test_firmador_803_diagnostico_5/certs
- Artefactos guardados en: /workspace/gestor-de-inventario/artifacts

## OK / contraseña correcta — PASS

- Escenario: `ok_password`
- Firmador 803: No
- Ruta diagnóstico JSON: artifacts/ok_password.json
- Flags:
  - sha512_match: True
  - cert_path_ok: True
  - cert_dir_mismatch: False
  - password_encoding_detected: None
  - multiple_crts: ['09061712791014.crt']
  - sha256_of_file: bca9fae4a6a703be0227b70a99b3a512ae5045aa4277268956a33f767b8b96c3
- NIT enviado: 09061712791014
- Archivo utilizado: 09061712791014.crt
- NIT dentro del CRT: 09061712791014
- Errores detectados: []
- Directorio efectivo: /tmp/pytest-of-root/pytest-0/test_firmador_803_diagnostico_0/certs
- Directorio del firmador: /tmp/pytest-of-root/pytest-0/test_firmador_803_diagnostico_0/certs
- Recomendación sugerida: El entorno básico funciona: no se detectaron errores.

## Contraseña incorrecta — PASS

- Escenario: `wrong_password`
- Firmador 803: Sí
- Ruta diagnóstico JSON: artifacts/wrong_password.json
- Flags:
  - sha512_match: False
  - cert_path_ok: True
  - cert_dir_mismatch: False
  - password_encoding_detected: None
  - multiple_crts: ['09061712791014.crt']
  - sha256_of_file: bca9fae4a6a703be0227b70a99b3a512ae5045aa4277268956a33f767b8b96c3
- NIT enviado: 09061712791014
- Archivo utilizado: 09061712791014.crt
- NIT dentro del CRT: 09061712791014
- Errores detectados: ['sha512_mismatch']
- Directorio efectivo: /tmp/pytest-of-root/pytest-0/test_firmador_803_diagnostico_1/certs
- Directorio del firmador: /tmp/pytest-of-root/pytest-0/test_firmador_803_diagnostico_1/certs
- Recomendación sugerida: Actualizar la contraseña para que coincida con el hash SHA-512 dentro del CRT.

## Contraseña almacenada en base64 sin decodificar — PASS

- Escenario: `password_base64`
- Firmador 803: Sí
- Ruta diagnóstico JSON: artifacts/password_base64.json
- Flags:
  - sha512_match: False
  - cert_path_ok: True
  - cert_dir_mismatch: False
  - password_encoding_detected: base64
  - multiple_crts: ['09061712791014.crt']
  - sha256_of_file: bca9fae4a6a703be0227b70a99b3a512ae5045aa4277268956a33f767b8b96c3
- NIT enviado: 09061712791014
- Archivo utilizado: 09061712791014.crt
- NIT dentro del CRT: 09061712791014
- Errores detectados: ['sha512_mismatch']
- Directorio efectivo: /tmp/pytest-of-root/pytest-0/test_firmador_803_diagnostico_2/certs
- Directorio del firmador: /tmp/pytest-of-root/pytest-0/test_firmador_803_diagnostico_2/certs
- Recomendación sugerida: Decodificar la contraseña base64 antes de calcular el hash SHA-512.

## Desincronización de directorios (CERT_UPLOAD_DIR) — PASS

- Escenario: `cert_dir_mismatch`
- Firmador 803: Sí
- Ruta diagnóstico JSON: artifacts/cert_dir_mismatch.json
- Flags:
  - sha512_match: True
  - cert_path_ok: True
  - cert_dir_mismatch: True
  - password_encoding_detected: None
  - multiple_crts: ['09061712791014.crt']
  - sha256_of_file: bca9fae4a6a703be0227b70a99b3a512ae5045aa4277268956a33f767b8b96c3
- NIT enviado: 09061712791014
- Archivo utilizado: 09061712791014.crt
- NIT dentro del CRT: 09061712791014
- Errores detectados: ['dir_mismatch']
- Directorio efectivo: /tmp/pytest-of-root/pytest-0/test_firmador_803_diagnostico_3/certs
- Directorio del firmador: /tmp/pytest-of-root/pytest-0/test_firmador_803_diagnostico_3/signer_dir
- Recomendación sugerida: Alinear CERT_UPLOAD_DIR y FIRMADOR_CERT_DIR para que ambos usen el mismo directorio.

## Múltiples CRT para el mismo NIT — PASS

- Escenario: `multiple_crts`
- Firmador 803: Sí
- Ruta diagnóstico JSON: artifacts/multiple_crts.json
- Flags:
  - sha512_match: True
  - cert_path_ok: True
  - cert_dir_mismatch: False
  - password_encoding_detected: None
  - multiple_crts: ['09061712791014(1).crt', '09061712791014.crt']
  - sha256_of_file: bca9fae4a6a703be0227b70a99b3a512ae5045aa4277268956a33f767b8b96c3
- NIT enviado: 09061712791014
- Archivo utilizado: 09061712791014.crt
- NIT dentro del CRT: 09061712791014
- Errores detectados: ['multiple_crts']
- Directorio efectivo: /tmp/pytest-of-root/pytest-0/test_firmador_803_diagnostico_4/certs
- Directorio del firmador: /tmp/pytest-of-root/pytest-0/test_firmador_803_diagnostico_4/certs
- Recomendación sugerida: Dejar un único archivo .crt por NIT y remover duplicados/renombrados.

## NIT mal normalizado — PASS

- Escenario: `nit_mismatch`
- Firmador 803: Sí
- Ruta diagnóstico JSON: artifacts/nit_mismatch.json
- Flags:
  - sha512_match: True
  - cert_path_ok: True
  - cert_dir_mismatch: False
  - password_encoding_detected: None
  - multiple_crts: ['09061712791015.crt']
  - sha256_of_file: bca9fae4a6a703be0227b70a99b3a512ae5045aa4277268956a33f767b8b96c3
- NIT enviado: 0906-171279-101-5
- Archivo utilizado: 09061712791015.crt
- NIT dentro del CRT: 09061712791014
- Errores detectados: ['nit_mismatch']
- Directorio efectivo: /tmp/pytest-of-root/pytest-0/test_firmador_803_diagnostico_5/certs
- Directorio del firmador: /tmp/pytest-of-root/pytest-0/test_firmador_803_diagnostico_5/certs
- Recomendación sugerida: Corregir el NIT configurado o regenerar el certificado para que coincidan.

## Causa más probable en este entorno

- Escenario: Contraseña incorrecta (`wrong_password`)
- Causa detectada: sha512_mismatch
- Recomendación: Actualizar la contraseña para que coincida con el hash SHA-512 dentro del CRT.
