# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_submodules, collect_data_files
from pathlib import Path
import base64
import certifi
import os

ICON_B64 = """
AAABAAEAAQEAAAEAIAAwAAAAFgAAACgAAAABAAAAAgAAAAEAIAAAAAAABAAAAAAAAAAAAAAAAAAA
AAAAAADliB7/AAAAAA==
""".strip().replace("\n", "")

icon_path = Path(__file__).resolve().parent.parent / 'assets' / 'app.ico'
if not icon_path.exists():
    icon_path.parent.mkdir(parents=True, exist_ok=True)
    icon_path.write_bytes(base64.b64decode(ICON_B64))

hidden = collect_submodules('PyQt5') + [
    'PyQt5.QtPrintSupport',
    'PyQt5.QtSvg',
]
datas = collect_data_files('PyQt5', include_py_files=False)
datas += [(certifi.where(), 'certifi')]

resource_folders = [
    'assets',
    'templates',
    'facturas_consumidor_final',
    'facturas_credito_fiscal',
    'notas_credito',
    'notas_debito',
    'notas_remision',
    'dtes',
    'dte_fallidos',
    'dtes_pendientes',
    'tickets',
    'svfe-json-schemas',
    'schema_patches',
]

for folder in resource_folders:
    if os.path.isdir(folder):
        datas.append((folder, folder))

for file_name in [
    'style.qss',
    'logoinventario.jpg',
    'formato_factura.json',
    'datos_negocio.json',
    'config_negocio.json',
    'inventario.json',
]:
    if os.path.isfile(file_name):
        datas.append((file_name, '.'))

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
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
    [],
    exclude_binaries=True,
    name='VertexDTE',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    icon=str(icon_path),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='VertexDTE',
)
