"""Signing helpers for DTE envelopes."""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Dict, Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.serialization import load_pem_private_key


_DEF_PRIV_KEY = "PrivateKey_000868547.key"


def _b64(data: bytes) -> bytes:
    return base64.urlsafe_b64encode(data).rstrip(b"=")


@dataclass
class LocalRS256Signer:
    """Simple RS256 signer using a local PEM private key."""

    key_path: str = _DEF_PRIV_KEY

    def __post_init__(self) -> None:
        try:
            with open(self.key_path, "rb") as fh:
                data = fh.read()
            self._key = load_pem_private_key(data, password=None)
        except Exception:
            # Fallback to an ephemeral key for testing if the PEM cannot be
            # loaded (e.g. missing or invalid file).
            from cryptography.hazmat.primitives.asymmetric import rsa

            self._key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def sign(self, payload: Dict[str, Any]) -> str:
        header = {"alg": "RS256", "typ": "JWS"}
        header_b64 = _b64(
            json.dumps(header, separators=(",", ":"), sort_keys=True).encode()
        )
        payload_b64 = _b64(
            json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        )
        signing_input = b".".join([header_b64, payload_b64])
        signature = self._key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
        token = b".".join([header_b64, payload_b64, _b64(signature)])
        return token.decode()


def sign_dte(envelope: Dict[str, Any], provider: str = "mh", signer: LocalRS256Signer | None = None) -> str:
    """Sign ``envelope`` returning a JWS token.

    In production the ``provider`` parameter would select the signing
    service. For tests a local RSA key is used via :class:`LocalRS256Signer`.
    """

    if signer is None:
        signer = LocalRS256Signer()
    return signer.sign(envelope)
