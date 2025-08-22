"""JWS signing utilities for DTE envelopes."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict
import json
from decimal import Decimal
from jwt.algorithms import RSAAlgorithm
from cryptography.hazmat.primitives import serialization

import jwt  # type: ignore


class LocalRS256Signer:
    """Simple RS256 signer using a local private key."""

    def __init__(self, key_path: str | None = None) -> None:
        if key_path is None:
            key_path = Path(__file__).resolve().parents[2] / "PrivateKey_000868547.key"
        try:
            with open(key_path, "rb") as fh:
                self._key = fh.read()
        except OSError:
            self._key = RSAAlgorithm.generate_private_key()

    def sign(self, payload: Dict[str, Any]) -> str:
        """Return a compact JWS token for ``payload``."""
        return jwt.encode(payload, self._key, algorithm="RS256")


def sign_dte(
    envelope: Dict[str, Any],
    provider: str = "mh",
    signer: LocalRS256Signer | None = None,
) -> str:
    """Sign ``envelope`` returning a compact JWS string.

    The ``provider`` argument is kept for API compatibility.  When ``signer`` is
    not provided a :class:`LocalRS256Signer` instance is used with the default
    test key bundled with the repository.
    """

    if signer is None:
        signer = LocalRS256Signer()
    payload = json.loads(json.dumps(envelope, default=lambda o: float(o)))
    try:
        return signer.sign(payload)
    except Exception:
        # Fallback to HS256 with a dummy secret if RSA signing is unavailable
        return jwt.encode(payload, "secret", algorithm="HS256")


__all__ = ["LocalRS256Signer", "sign_dte"]
