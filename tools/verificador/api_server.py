"""Servidor HTTP ligero para exponer el estado del verificador.

Este módulo administra la configuración local persistente y ofrece una
interfaz para levantar un pequeño servidor HTTP(S) que publica información
de salud y acepta pings autenticados.
"""

from __future__ import annotations

import base64
import hmac
import json
import logging
import secrets
import ssl
import threading
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from time import time
from typing import Any, Dict, Optional
from uuid import uuid4

LOGGER = logging.getLogger("verificador.api")


DEFAULT_PORT = 8443
CONFIG_FILENAME = "verificador_config.json"
CERT_DIRNAME = "certs"
CERT_FILE = "cert.pem"
KEY_FILE = "key.pem"


def _generate_shared_secret() -> str:
    token = secrets.token_bytes(32)
    return base64.urlsafe_b64encode(token).decode("ascii").rstrip("=")


@dataclass
class LocalServerConfig:
    instance_id: str
    listen_port: int = DEFAULT_PORT
    shared_secret: str = field(default_factory=_generate_shared_secret)
    public_hint: str = ""

    @classmethod
    def load(cls, path: Path) -> "LocalServerConfig":
        if not path.exists():
            config = cls(instance_id=str(uuid4()))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(config.to_dict(), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            return config

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            LOGGER.warning("Configuración local inválida, se regenerará: %s", path)
            data = {}
        instance_id = data.get("instance_id") or str(uuid4())
        try:
            listen_port = int(data.get("listen_port", DEFAULT_PORT))
        except (TypeError, ValueError):
            LOGGER.warning("Puerto inválido en configuración local, se usará %s", DEFAULT_PORT)
            listen_port = DEFAULT_PORT
        shared_secret = data.get("shared_secret")
        if not isinstance(shared_secret, str) or not shared_secret.strip():
            shared_secret = _generate_shared_secret()
        public_hint = data.get("public_hint", "")
        if not isinstance(public_hint, str):
            public_hint = ""
        config = cls(
            instance_id=instance_id,
            listen_port=listen_port,
            shared_secret=shared_secret,
            public_hint=public_hint,
        )
        # Persistimos cualquier corrección (por ejemplo, campos faltantes)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(config.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return config

    def to_dict(self) -> Dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            "listen_port": self.listen_port,
            "shared_secret": self.shared_secret,
            "public_hint": self.public_hint,
        }


class _ThreadingServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class _RequestHandler(BaseHTTPRequestHandler):
    server_version = "VertexVerifier/1.0"

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler signature
        if self.path.rstrip("/") == "/health":
            self._handle_health()
            return
        self._send_json({"error": "not_found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler signature
        if self.path.rstrip("/") == "/ping":
            if not self._require_auth():
                return
            self._handle_ping()
            return
        self._send_json({"error": "not_found"}, HTTPStatus.NOT_FOUND)

    # --- Helpers ---
    def log_message(self, format: str, *args: object) -> None:  # noqa: A003 - name inherited
        LOGGER.info("%s - %s", self.address_string(), format % args)

    @property
    def _server(self) -> "VerifierApiServer":
        return self.server.server_manager  # type: ignore[attr-defined]

    def _handle_health(self) -> None:
        payload = {
            "ok": True,
            "instance_id": self._server.config.instance_id,
            "ts": int(time()),
            "mode": self._server.mode,
            "port": self._server.listening_port,
        }
        if self._server.config.public_hint:
            payload["public_hint"] = self._server.config.public_hint
        self._send_json(payload)

    def _handle_ping(self) -> None:
        length_header = self.headers.get("Content-Length", "0")
        try:
            length = int(length_header)
        except ValueError:
            self._send_json({"error": "invalid_length"}, HTTPStatus.BAD_REQUEST)
            return

        raw = self.rfile.read(length) if length > 0 else b"{}"
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self._send_json({"error": "invalid_json"}, HTTPStatus.BAD_REQUEST)
            return

        payload = {
            "ok": True,
            "instance_id": self._server.config.instance_id,
            "ts": int(time()),
            "echo": data,
        }
        self._send_json(payload)

    def _require_auth(self) -> bool:
        header = self.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            self._send_json({"error": "missing_token"}, HTTPStatus.UNAUTHORIZED)
            return False
        token = header.split(" ", 1)[1]
        expected = self._server.config.shared_secret
        if not hmac.compare_digest(token, expected):
            self._send_json({"error": "invalid_token"}, HTTPStatus.FORBIDDEN)
            return False
        return True

    def _send_json(self, payload: Dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class VerifierApiServer:
    """Gestiona el ciclo de vida del servidor HTTP(S)."""

    def __init__(self, app_root: Path) -> None:
        self.app_root = app_root
        self.config_path = self.app_root / CONFIG_FILENAME
        self.config = LocalServerConfig.load(self.config_path)
        self.mode = "http"
        self._server: Optional[_ThreadingServer] = None
        self._thread: Optional[threading.Thread] = None
        self._listening_port = int(self.config.listen_port)

    def start(self) -> bool:
        if self._server is not None:
            return True

        address = ("0.0.0.0", int(self.config.listen_port))
        try:
            httpd = _ThreadingServer(address, _RequestHandler)
        except OSError as exc:
            LOGGER.error("No se pudo iniciar el servidor API: %s", exc)
            return False

        httpd.server_manager = self  # type: ignore[attr-defined]
        self._listening_port = httpd.server_address[1]

        cert_dir = self.app_root / CERT_DIRNAME
        cert_path = cert_dir / CERT_FILE
        key_path = cert_dir / KEY_FILE
        if cert_path.exists() and key_path.exists():
            try:
                context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                context.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))
                httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
                self.mode = "https"
            except Exception as exc:  # pragma: no cover - configuración externa
                LOGGER.error("No se pudo habilitar HTTPS: %s", exc)
                self.mode = "http"
        else:
            self.mode = "http"

        thread = threading.Thread(target=httpd.serve_forever, name="VerifierApiServer", daemon=True)
        thread.start()

        self._server = httpd
        self._thread = thread
        LOGGER.info(
            "Servidor API iniciado en %s://0.0.0.0:%s", self.mode, self.listening_port
        )
        return True

    def shutdown(self) -> None:
        if not self._server:
            return
        LOGGER.info("Deteniendo servidor API")
        self._server.shutdown()
        self._server.server_close()
        if self._thread:
            self._thread.join(timeout=2.0)
        self._server = None
        self._thread = None

    def reload_config(self) -> None:
        self.config = LocalServerConfig.load(self.config_path)

    @property
    def listening_port(self) -> int:
        return self._listening_port


__all__ = ["VerifierApiServer", "LocalServerConfig"]
