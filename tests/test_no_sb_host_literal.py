from pathlib import Path

NEEDLE = "sand" + "box.dtes." + "mh.gob.sv"


def test_repo_has_no_sb_host_literal():
    root = Path(__file__).resolve().parents[1]
    for path in root.rglob("*"):
        if ".git" in path.parts or "node_modules" in path.parts:
            continue
        if path.is_file():
            try:
                text = path.read_text(encoding="utf-8")
            except Exception:
                continue
            assert NEEDLE not in text, f"{NEEDLE} found in {path}"
