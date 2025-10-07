"""Backends para la herramienta de verificación de licencias de Vertex.

Este módulo define la interfaz común de backends y la implementación por
defecto basada en carpetas compartidas SMB. También deja un esqueleto para un
backend HTTP local que se implementará en fases posteriores.
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519


@dataclass
class AdminConfig:
    """Configuración persistente del verificador."""

    mode: str = "share"
    share_path: str = r"\\\\PC_ADMIN\\LicenciasVertex\\"
    licenses_path: str = r"\\\\PC_ADMIN\\LicenciasVertex\\licenses\\"
    requests_path: str = r"\\\\PC_ADMIN\\LicenciasVertex\\requests\\"
    public_key_path: str = "tools/verificador/keys/license_pub.pem"
    private_key_path: str = "tools/verificador/keys/license_priv.pem"

    def to_dict(self) -> Dict[str, str]:
        return {
            "mode": self.mode,
            "share_path": self.share_path,
            "licenses_path": self.licenses_path,
            "requests_path": self.requests_path,
            "public_key_path": self.public_key_path,
            "private_key_path": self.private_key_path,
        }

    @classmethod
    def from_path(cls, path: Path) -> "AdminConfig":
        if not path.exists():
            config = cls()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(config.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
            return config

        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(**data)

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")


@dataclass
class LicenseRecord:
    """Representa un archivo de licencia emitido."""

    alias: str
    device_id: str
    status: str
    expires_at: Optional[str]
    grace_until: Optional[str]
    issued_at: str
    notes: str = ""
    last_sync: Optional[str] = None
    signature: Optional[str] = None
    path: Optional[Path] = None
    extra_fields: Dict[str, object] = field(default_factory=dict)

    def canonical_payload(self) -> Dict[str, Optional[str]]:
        return {
            "device_id": self.device_id,
            "status": self.status,
            "expires_at": self.expires_at,
            "grace_until": self.grace_until,
            "issued_at": self.issued_at,
        }


@dataclass
class LicenseRequest:
    """Solicitud de alta generada por un cliente."""

    device_id: str
    alias: str = ""
    notes: str = ""
    requested_at: Optional[str] = None
    path: Optional[Path] = None
    raw_payload: Dict[str, object] = field(default_factory=dict)


class LicenseBackend:
    """Interfaz base para gestionar licencias."""

    def __init__(self, config_path: Path) -> None:
        self.config_path = config_path
        self.config = AdminConfig.from_path(config_path)

    # --- Métodos comunes ---
    def reload_config(self) -> AdminConfig:
        self.config = AdminConfig.from_path(self.config_path)
        return self.config

    def save_config(self, config: AdminConfig) -> None:
        self.config = config
        config.save(self.config_path)

    # --- Operaciones abstractas ---
    def list_licenses(self) -> List[LicenseRecord]:  # pragma: no cover - interfaz
        raise NotImplementedError

    def list_requests(self) -> List[LicenseRequest]:  # pragma: no cover - interfaz
        raise NotImplementedError

    def create_license(self, *, alias: str, device_id: str, status: str) -> LicenseRecord:  # pragma: no cover
        raise NotImplementedError

    def save_license(self, record: LicenseRecord) -> LicenseRecord:  # pragma: no cover
        raise NotImplementedError

    def remove_request(self, request: LicenseRequest) -> None:  # pragma: no cover
        raise NotImplementedError

    # --- Operaciones auxiliares ---
    @staticmethod
    def now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()


class ShareBackend(LicenseBackend):
    """Backend que trabaja directamente con una carpeta compartida SMB."""

    def __init__(self, config_path: Path) -> None:
        super().__init__(config_path)
        self._licenses_dir = Path(self.config.licenses_path)
        self._requests_dir = Path(self.config.requests_path)

    # --- Utilidades internas ---
    @property
    def private_key_path(self) -> Path:
        return Path(self.config.private_key_path)

    @property
    def public_key_path(self) -> Path:
        return Path(self.config.public_key_path)

    def ensure_directories(self) -> None:
        self._licenses_dir.mkdir(parents=True, exist_ok=True)
        self._requests_dir.mkdir(parents=True, exist_ok=True)
        if self.public_key_path.parent != Path("."):
            self.public_key_path.parent.mkdir(parents=True, exist_ok=True)
        if self.private_key_path.parent != Path("."):
            self.private_key_path.parent.mkdir(parents=True, exist_ok=True)

    # --- Claves ---
    def private_key(self) -> Optional[ed25519.Ed25519PrivateKey]:
        if not self.private_key_path.exists():
            return None
        data = self.private_key_path.read_bytes()
        return serialization.load_pem_private_key(data, password=None)

    def public_key(self) -> Optional[ed25519.Ed25519PublicKey]:
        if not self.public_key_path.exists():
            return None
        data = self.public_key_path.read_bytes()
        return serialization.load_pem_public_key(data)

    def generate_keys(self) -> None:
        self.ensure_directories()
        private_key = ed25519.Ed25519PrivateKey.generate()
        public_key = private_key.public_key()

        priv_bytes = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        pub_bytes = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )

        self.private_key_path.write_bytes(priv_bytes)
        self.public_key_path.write_bytes(pub_bytes)

    # --- Lectura ---
    def list_licenses(self) -> List[LicenseRecord]:
        self.ensure_directories()
        records: List[LicenseRecord] = []
        if not self._licenses_dir.exists():
            return records

        for path in sorted(self._licenses_dir.glob("*.json")):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue

            record = LicenseRecord(
                alias=raw.get("alias", ""),
                device_id=raw.get("device_id", path.stem),
                status=raw.get("status", "UNKNOWN"),
                expires_at=raw.get("expires_at"),
                grace_until=raw.get("grace_until"),
                issued_at=raw.get("issued_at", ""),
                notes=raw.get("notes", ""),
                last_sync=raw.get("last_sync"),
                signature=raw.get("signature"),
                path=path,
                extra_fields={k: v for k, v in raw.items() if k not in {
                    "alias",
                    "device_id",
                    "status",
                    "expires_at",
                    "grace_until",
                    "issued_at",
                    "notes",
                    "last_sync",
                    "signature",
                }},
            )
            records.append(record)

        return records

    def list_requests(self) -> List[LicenseRequest]:
        self.ensure_directories()
        requests: List[LicenseRequest] = []
        if not self._requests_dir.exists():
            return requests

        for path in sorted(self._requests_dir.glob("*.json")):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue

            requests.append(
                LicenseRequest(
                    device_id=raw.get("device_id", path.stem),
                    alias=raw.get("alias", ""),
                    notes=raw.get("notes", ""),
                    requested_at=raw.get("requested_at"),
                    path=path,
                    raw_payload=raw,
                )
            )

        return requests

    # --- Escritura ---
    def create_license(self, *, alias: str, device_id: str, status: str) -> LicenseRecord:
        issued_at = self.now_iso()
        record = LicenseRecord(
            alias=alias,
            device_id=device_id,
            status=status,
            expires_at=None,
            grace_until=None,
            issued_at=issued_at,
            notes="",
            last_sync=None,
            path=self._licenses_dir / f"{device_id}.json",
        )
        return self.save_license(record)

    def save_license(self, record: LicenseRecord) -> LicenseRecord:
        private_key = self.private_key()
        if private_key is None:
            raise RuntimeError(
                "No se encontró la clave privada. Genere un par de claves antes de emitir licencias."
            )

        payload = record.canonical_payload()
        canonical = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        signature = private_key.sign(canonical.encode("utf-8"))
        signature_b64 = base64.b64encode(signature).decode("ascii")

        data = {
            **payload,
            "alias": record.alias,
            "notes": record.notes,
            "last_sync": record.last_sync,
            **record.extra_fields,
            "signature": signature_b64,
        }

        record.signature = signature_b64
        if record.path is None:
            record.path = self._licenses_dir / f"{record.device_id}.json"

        record.path.parent.mkdir(parents=True, exist_ok=True)
        record.path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return record

    def remove_request(self, request: LicenseRequest) -> None:
        if request.path and request.path.exists():
            try:
                request.path.unlink()
            except OSError:
                pass

    # --- Acciones de negocio ---
    def update_status(self, record: LicenseRecord, status: str) -> LicenseRecord:
        record.status = status
        return self.save_license(record)

    def set_expiration(self, record: LicenseRecord, expires_at: Optional[str]) -> LicenseRecord:
        record.expires_at = expires_at
        return self.save_license(record)

    def set_grace_until(self, record: LicenseRecord, grace_until: Optional[str]) -> LicenseRecord:
        record.grace_until = grace_until
        return self.save_license(record)


class HttpBackend(LicenseBackend):
    """Futuro backend HTTP.

    Esta clase servirá para comunicarse con una API local que exponga los mismos
    flujos que el backend de carpetas compartidas. En esta fase no se implementa
    la lógica, pero se documentan los métodos esperados para facilitar el
    desarrollo posterior.
    """

    def list_licenses(self) -> List[LicenseRecord]:  # pragma: no cover - stub
        raise NotImplementedError("HttpBackend aún no está implementado.")

    def list_requests(self) -> List[LicenseRequest]:  # pragma: no cover - stub
        raise NotImplementedError("HttpBackend aún no está implementado.")

    def create_license(self, *, alias: str, device_id: str, status: str) -> LicenseRecord:  # pragma: no cover - stub
        raise NotImplementedError("HttpBackend aún no está implementado.")

    def save_license(self, record: LicenseRecord) -> LicenseRecord:  # pragma: no cover - stub
        raise NotImplementedError("HttpBackend aún no está implementado.")

    def remove_request(self, request: LicenseRequest) -> None:  # pragma: no cover - stub
        raise NotImplementedError("HttpBackend aún no está implementado.")

