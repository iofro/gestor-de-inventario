import base64
import hashlib
import json
import shutil
import threading
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, Iterable, Optional
from urllib.parse import parse_qs, urlparse

import pytest

import paths
from utils import jws
from utils.certificates import run_certificate_doctor


ERROR_803 = {
    "status": "ERROR",
    "body": {"codigo": "803", "mensaje": "No existe llave publica para este nit"},
}


def _sha512(text: str) -> str:
    return hashlib.sha512(text.encode("utf-8")).hexdigest()


def _compute_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(8192), b""):
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _parse_certificate(path: Path) -> tuple[Optional[str], Optional[str]]:
    data = path.read_text(encoding="utf-8")
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return None, None
    nit_node = root.find(".//nit")
    clave_node = root.find(".//privateKey/clave")
    nit_value = nit_node.text.strip() if nit_node is not None and nit_node.text else None
    clave_value = clave_node.text.strip() if clave_node is not None and clave_node.text else None
    return nit_value, clave_value


def create_certificate(path: Path, nit: str, password_plain: str) -> None:
    xml = (
        "<CertificadoMH>"
        f"<nit>{nit}</nit>"
        "<privateKey><clave>"
        f"{_sha512(password_plain)}"
        "</clave></privateKey>"
        "</CertificadoMH>"
    )
    path.write_text(xml, encoding="utf-8")


class _SignerHandler(BaseHTTPRequestHandler):
    server: "SignerDebugServer"

    def log_message(self, format: str, *args) -> None:  # pragma: no cover - silence logs
        return

    def _json_response(self, payload: Dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/firma/debug/certs":
            nit = parse_qs(parsed.query or "").get("n", [None])[0]
            payload = self.server.build_certs_payload(nit)
            self._json_response(payload)
            return
        if parsed.path == "/firma/debug/env":
            self._json_response({"env": self.server.env})
            return
        self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        body = json.loads(raw or b"{}")
        if parsed.path == "/firma/debug/hash":
            password = body.get("passwordPri", "")
            self._json_response({"password_sha512": _sha512(password)})
            return
        if parsed.path == "/firma/firmardocumento/":
            self._json_response(self.server.sign_response)
            return
        self.send_error(404)


class SignerDebugServer(ThreadingHTTPServer):
    def __init__(self, cert_dir: Path, env: Dict[str, str], sign_response: Dict):
        super().__init__(("127.0.0.1", 0), _SignerHandler)
        self.cert_dir = cert_dir
        self.env = env
        self.sign_response = sign_response

    def build_certs_payload(self, nit: Optional[str]) -> Dict:
        files: list[Dict[str, object]] = []
        selected: Optional[Path] = None
        normalized = "".join(ch for ch in nit or "" if ch.isdigit())
        entries = sorted(self.cert_dir.glob("*.crt"))
        for entry in entries:
            info = {
                "name": entry.name,
                "size": entry.stat().st_size,
                "sha256": _compute_sha256(entry),
            }
            files.append(info)
            if normalized and entry.stem == normalized:
                selected = entry
        if not selected and entries:
            selected = entries[0]
        nit_from_crt = None
        cert_password_sha512 = None
        cert_sha256 = None
        if selected and selected.exists():
            nit_from_crt, cert_password_sha512 = _parse_certificate(selected)
            cert_sha256 = _compute_sha256(selected)
        return {
            "signer_cert_dir": str(self.cert_dir),
            "env": self.env,
            "files": files,
            "selected": selected.name if selected else None,
            "nit_from_crt": nit_from_crt,
            "cert_password_sha512": cert_password_sha512,
            "cert_sha256": cert_sha256,
        }


@dataclass
class SignerStub:
    cert_dir: Path
    env: Dict[str, str]
    sign_response: Dict = field(default_factory=lambda: ERROR_803)

    def __post_init__(self) -> None:
        self._server = SignerDebugServer(self.cert_dir, self.env, self.sign_response)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def __enter__(self) -> "SignerStub":
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._server.shutdown()
        self._thread.join()

    @property
    def sign_url(self) -> str:
        host, port = self._server.server_address
        return f"http://{host}:{port}/firma/firmardocumento/"


@dataclass
class DoctorScenario:
    name: str
    nit: str
    cert_nit: str
    password_plain: str
    password_input: str
    expected_issues: set[str]
    remote_dir_mismatch: bool = False
    extra_local: Iterable[str] = ()
    extra_remote: Iterable[str] = ()
    remote_env_override: Optional[Dict[str, str]] = None


SCENARIOS = [
    DoctorScenario(
        name="ok_password",
        nit="09061712791014",
        cert_nit="09061712791014",
        password_plain="clave-correcta",
        password_input="clave-correcta",
        expected_issues=set(),
    ),
    DoctorScenario(
        name="wrong_password",
        nit="09061712791014",
        cert_nit="09061712791014",
        password_plain="clave-correcta",
        password_input="clave-incorrecta",
        expected_issues={"sha512_mismatch"},
    ),
    DoctorScenario(
        name="password_base64",
        nit="09061712791014",
        cert_nit="09061712791014",
        password_plain="clave-correcta",
        password_input=base64.b64encode(b"clave-correcta").decode("ascii"),
        expected_issues={"password_encoding_base64", "sha512_mismatch"},
    ),
    DoctorScenario(
        name="cert_dir_mismatch",
        nit="09061712791014",
        cert_nit="09061712791014",
        password_plain="clave-correcta",
        password_input="clave-correcta",
        expected_issues={"dir_mismatch"},
        remote_dir_mismatch=True,
    ),
    DoctorScenario(
        name="multiple_crts",
        nit="09061712791014",
        cert_nit="09061712791014",
        password_plain="clave-correcta",
        password_input="clave-correcta",
        expected_issues={"multiple_crts"},
        extra_local=["09061712791014_backup.crt"],
        extra_remote=["09061712791014_backup.crt"],
    ),
    DoctorScenario(
        name="nit_mismatch",
        nit="09061712791015",
        cert_nit="09061712791014",
        password_plain="clave-correcta",
        password_input="clave-correcta",
        expected_issues={"nit_mismatch"},
    ),
]


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda sc: sc.name)
def test_run_certificate_doctor_scenarios(
    scenario: DoctorScenario,
    tmp_path: Path,
    artifacts_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    local_dir = tmp_path / "certs_local"
    local_dir.mkdir()
    if scenario.remote_dir_mismatch:
        remote_dir = tmp_path / "certs_remote"
        remote_dir.mkdir()
    else:
        remote_dir = local_dir

    normalized = "".join(ch for ch in scenario.nit if ch.isdigit())
    file_stem = normalized or scenario.nit
    main_local = local_dir / f"{file_stem}.crt"
    create_certificate(main_local, scenario.cert_nit, scenario.password_plain)
    if remote_dir is not local_dir:
        shutil.copy2(main_local, remote_dir / main_local.name)

    for extra in scenario.extra_local:
        create_certificate(local_dir / extra, scenario.cert_nit, scenario.password_plain)
    for extra in scenario.extra_remote:
        target = remote_dir / extra
        if remote_dir is local_dir and target.exists():
            continue
        create_certificate(target, scenario.cert_nit, scenario.password_plain)

    base_env = {
        "CERT_UPLOAD_DIR": str(remote_dir),
        "FIRMADOR_CERT_DIR": str(remote_dir),
    }
    if scenario.remote_env_override:
        base_env.update(scenario.remote_env_override)

    monkeypatch.setenv("CERT_UPLOAD_DIR", str(local_dir))
    monkeypatch.setenv("FIRMADOR_CERT_DIR", str(remote_dir))

    with SignerStub(remote_dir, base_env) as stub:
        output_dir = tmp_path / "diagnostics" / scenario.name
        report = run_certificate_doctor(
            nit=scenario.nit,
            password=scenario.password_input,
            signer_url=stub.sign_url,
            cert_dir=str(local_dir),
            output_dir=output_dir,
        )

    issues = set(report.data["issues"])
    for expected in scenario.expected_issues:
        assert expected in issues
    if scenario.expected_issues:
        assert not report.data["ok"]
    else:
        assert report.data["ok"]

    assert report.data["probable_cause"]
    assert report.data["remediation"]

    artifact_dir = artifacts_dir / scenario.name
    artifact_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(report.json_path, artifact_dir / "cert_diagnosis.json")
    shutil.copy2(report.markdown_path, artifact_dir / "cert_diagnosis.md")


def test_sign_json_attaches_diagnosis_on_803(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    local_dir = tmp_path / "certs"
    remote_dir = tmp_path / "remote"
    local_dir.mkdir()
    remote_dir.mkdir()

    nit = "09061712791014"
    create_certificate(local_dir / f"{nit}.crt", nit, "clave-correcta")
    shutil.copy2(local_dir / f"{nit}.crt", remote_dir / f"{nit}.crt")

    user_data_dir = tmp_path / "user_data"
    monkeypatch.setattr(paths, "USER_DATA_DIR", user_data_dir)
    monkeypatch.setattr(paths, "CERT_UPLOAD_DIR", str(local_dir))
    monkeypatch.setattr(jws, "CERT_UPLOAD_DIR", str(local_dir))
    monkeypatch.setenv("CERT_UPLOAD_DIR", str(local_dir))
    monkeypatch.setenv("FIRMADOR_CERT_DIR", str(remote_dir))

    base_env = {
        "CERT_UPLOAD_DIR": str(remote_dir),
        "FIRMADOR_CERT_DIR": str(remote_dir),
    }

    with SignerStub(remote_dir, base_env) as stub:
        payload = {"identificacion": {"version": "1", "tipoDte": "01"}, "dummy": True}
        with pytest.raises(RuntimeError) as excinfo:
            jws.sign_json(
                payload,
                nit=nit,
                passwordPri="clave-incorrecta",
                activo=True,
                url=stub.sign_url,
            )

    message = str(excinfo.value)
    assert "803" in message
    assert "diagnosis:" in message
    diag_dir = user_data_dir / "diagnostics"
    json_path = diag_dir / "cert_diagnosis.json"
    markdown_path = diag_dir / "cert_diagnosis.md"
    assert json_path.exists()
    assert markdown_path.exists()

    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert "issues" in data
    assert "sha512_mismatch" in data.get("issues", []) or "local" in data
