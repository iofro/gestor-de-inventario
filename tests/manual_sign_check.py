import os
import requests


def build_minimal_dte():
    """Return a minimal DTE payload with ambiente="00"."""
    return {
        "identificacion": {
            "ambiente": "00",
        }
    }


def main():
    sign_url = os.getenv("SIGN_URL")
    nit = os.getenv("NIT_FIRMADOR")

    if not sign_url or not nit:
        print("SIGN_TEST_FAIL", "MISSING_ENV")
        return

    payload = {"nit": nit, "dteJson": build_minimal_dte()}

    status = 0
    try:
        response = requests.post(sign_url, json=payload, timeout=10)
        status = response.status_code
        if (
            status == 200
            and response.headers.get("content-type", "").startswith("application/json")
        ):
            data = response.json()
            if data.get("status") == "OK" and data.get("body"):
                print("SIGN_TEST_OK")
                return
    except requests.RequestException as exc:
        if hasattr(exc, "response") and exc.response is not None:
            status = exc.response.status_code
    print("SIGN_TEST_FAIL", status)


if __name__ == "__main__":
    main()
