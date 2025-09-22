# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import base64

from PyInstaller.utils.hooks import collect_submodules, collect_data_files
import certifi

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ICON_DIR = PROJECT_ROOT / "assets"
ICON_FILE = ICON_DIR / "app.ico"
ICON_B64 = ICON_DIR / "app.ico.b64"

if not ICON_FILE.exists() and ICON_B64.exists():
    ICON_FILE.write_bytes(base64.b64decode(ICON_B64.read_text()))

hidden = sorted(set(collect_submodules("PyQt5") + [
    "PyQt5.QtPrintSupport",
    "PyQt5.QtSvg",
]))

datas = collect_data_files("PyQt5", include_py_files=False)
datas += [(certifi.where(), "certifi")]

resource_dirs = [
    "assets",
    "templates",
    "facturas_consumidor_final",
    "facturas_credito_fiscal",
    "notas_credito",
    "notas_debito",
    "notas_remision",
    "dtes",
    "dtes_pendientes",
    "dte_fallidos",
    "tickets",
    "svfe-json-schemas",
    "schema_patches",
    "print",
]

for folder in resource_dirs:
    folder_path = PROJECT_ROOT / folder
    if folder_path.is_dir():
        datas.append((str(folder_path), folder))

resource_files = [
    "app_version.ini",
    "datos_negocio.json",
    "config_negocio.json",
    "inventario.json",
    "style.qss",
    "logoinventario.jpg",
]

for file_name in resource_files:
    file_path = PROJECT_ROOT / file_name
    if file_path.is_file():
        datas.append((str(file_path), file_path.name))

block_cipher = None

a = Analysis(
    [str(PROJECT_ROOT / "main.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="VertexDTE",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON_FILE),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="VertexDTE",
)
