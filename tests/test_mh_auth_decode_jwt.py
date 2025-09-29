import base64
import json

from mh_auth import decode_jwt_claims


def _make_token(payload: dict) -> str:
    header = base64.urlsafe_b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode("utf-8")).decode("ascii").rstrip("=")
    body = base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("ascii").rstrip("=")
    return f"{header}.{body}.signature"


def test_decode_jwt_claims_extracts_known_fields():
    payload = {
        "sub": "1234567890",
        "iat": 1_700_000_000,
        "exp": 1_700_000_900,
        "roles": ["a", "b", "c"],
        "ignored": "value",
    }
    token = _make_token(payload)
    claims = decode_jwt_claims(f"Bearer {token}")
    assert claims == {
        "sub": payload["sub"],
        "iat": payload["iat"],
        "exp": payload["exp"],
        "roles": payload["roles"],
    }


def test_decode_jwt_claims_handles_invalid_inputs():
    assert decode_jwt_claims(None) == {}
    assert decode_jwt_claims("") == {}
    assert decode_jwt_claims("Bearer not-a-jwt") == {}
    assert decode_jwt_claims("Basic abc") == {}
