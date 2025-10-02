# Diagnóstico de certificados


## Resumen


* **OK:** False
* **Problemas detectados:** password_encoding_base64, sha512_mismatch
* **Causa probable:** La contraseña no coincide con el hash del certificado
* **Remediación sugerida:** Verifica la contraseña configurada y vuelve a cargar el certificado correcto.


## Entorno local


```json
{
  "cert_dir": "/tmp/pytest-of-root/pytest-2/test_run_certificate_doctor_sc2/certs_local",
  "cert_dir_source": "parameter",
  "default_cert_dir": "/root/.local/share/VertexDTE/certificados",
  "signer_cert_dir": "/tmp/pytest-of-root/pytest-2/test_run_certificate_doctor_sc2/certs_local",
  "nit_config": "09061712791014",
  "nit_crt": "09061712791014",
  "cert_path": "/tmp/pytest-of-root/pytest-2/test_run_certificate_doctor_sc2/certs_local/09061712791014.crt",
  "cert_exists": true,
  "cert_size": 224,
  "cert_sha256": "bca9fae4a6a703be0227b70a99b3a512ae5045aa4277268956a33f767b8b96c3",
  "password_sha512": "58fa9a9426f6789ccd101d86a637fbdb31226360a2ca1d0a2f3b9a83815fd611cb9a2f408ff9594d87d209b97ba432c5cbd2c810b59b085ba728b782e2587384",
  "cert_password_sha512": "c7ac71334b275042d2c7e7a9cf1fcbbdec6e35239ad625b1372bdd911e73b4cf514074b51c5122efa7a894a4950b5a07b57757fa8e5802567bd53eb7141142f4",
  "multiple_crts": [
    "09061712791014.crt"
  ],
  "parse_error": null,
  "errors": [
    "sha512_mismatch"
  ],
  "ok": false
}
```


## Entorno del firmador


```json
{
  "available": true,
  "error": null,
  "status_code": 200,
  "signer_cert_dir": "/tmp/pytest-of-root/pytest-2/test_run_certificate_doctor_sc2/certs_local",
  "env": {
    "CERT_UPLOAD_DIR": "/tmp/pytest-of-root/pytest-2/test_run_certificate_doctor_sc2/certs_local",
    "FIRMADOR_CERT_DIR": "/tmp/pytest-of-root/pytest-2/test_run_certificate_doctor_sc2/certs_local"
  },
  "files": [
    {
      "name": "09061712791014.crt",
      "size": 224,
      "sha256": "bca9fae4a6a703be0227b70a99b3a512ae5045aa4277268956a33f767b8b96c3"
    }
  ],
  "selected": "09061712791014.crt",
  "nit_from_crt": "09061712791014",
  "cert_password_sha512": "c7ac71334b275042d2c7e7a9cf1fcbbdec6e35239ad625b1372bdd911e73b4cf514074b51c5122efa7a894a4950b5a07b57757fa8e5802567bd53eb7141142f4",
  "cert_sha256": "bca9fae4a6a703be0227b70a99b3a512ae5045aa4277268956a33f767b8b96c3",
  "password_sha512": "58fa9a9426f6789ccd101d86a637fbdb31226360a2ca1d0a2f3b9a83815fd611cb9a2f408ff9594d87d209b97ba432c5cbd2c810b59b085ba728b782e2587384",
  "env_available": true
}
```


## Comparaciones


```json
{
  "cert_sha256": {
    "local": "bca9fae4a6a703be0227b70a99b3a512ae5045aa4277268956a33f767b8b96c3",
    "remote": "bca9fae4a6a703be0227b70a99b3a512ae5045aa4277268956a33f767b8b96c3",
    "match": true
  },
  "cert_password_sha512": {
    "local": "c7ac71334b275042d2c7e7a9cf1fcbbdec6e35239ad625b1372bdd911e73b4cf514074b51c5122efa7a894a4950b5a07b57757fa8e5802567bd53eb7141142f4",
    "remote": "c7ac71334b275042d2c7e7a9cf1fcbbdec6e35239ad625b1372bdd911e73b4cf514074b51c5122efa7a894a4950b5a07b57757fa8e5802567bd53eb7141142f4",
    "match": true
  },
  "password_sha512": {
    "local": "58fa9a9426f6789ccd101d86a637fbdb31226360a2ca1d0a2f3b9a83815fd611cb9a2f408ff9594d87d209b97ba432c5cbd2c810b59b085ba728b782e2587384",
    "remote": "58fa9a9426f6789ccd101d86a637fbdb31226360a2ca1d0a2f3b9a83815fd611cb9a2f408ff9594d87d209b97ba432c5cbd2c810b59b085ba728b782e2587384",
    "match": true
  }
}
```
