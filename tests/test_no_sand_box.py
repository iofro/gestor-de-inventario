from pathlib import Path

NEEDLE = "sand" + "box"


def test_repo_has_no_sand_box():
    root = Path(__file__).resolve().parents[1]
    for path in root.rglob("*"):
        if ".git" in path.parts or "node_modules" in path.parts:
            continue
        if path.is_file():
            try:
                text = path.read_text(encoding="utf-8")
            except Exception:
                continue
            assert NEEDLE not in text.lower(), f"{NEEDLE} found in {path}"
