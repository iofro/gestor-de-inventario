# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_data_files, collect_submodules
import os
import sys
from pathlib import Path

icon_path = 'assets/app.ico'
if not os.path.isfile(icon_path):
    icon_path = None

hidden = collect_submodules('PyQt5') + [
    'PyQt5.QtPrintSupport',
    'PyQt5.QtSvg',
]
hidden = sorted(set(hidden))

datas = collect_data_files('PyQt5', include_py_files=False)
datas += collect_data_files('certifi', include_py_files=False)

spec_path = Path(locals().get('__file__', sys.argv[0])).resolve()
repo_root = spec_path.parent.parent

resource_directories = [
    'assets',
    'templates',
    'dtes',
    'dte_fallidos',
    'dtes_pendientes',
    'schema_patches',
    'svfe-json-schemas',
    'tickets',
]

for pattern in ['facturas_*', 'notas_*']:
    for match in repo_root.glob(pattern):
        if match.is_dir():
            resource_directories.append(str(match.relative_to(repo_root)))

firmador_dir = os.path.join('extras', 'firmador')
resource_directories.append(firmador_dir)

for directory in resource_directories:
    source = repo_root / directory
    if source.is_dir():
        datas.append((str(source), directory))

for file_name in [
    'style.qss',
    'logoinventario.jpg',
    'formato_factura.json',
    'datos_negocio.json',
    'config_negocio.json',
    'inventario.json',
]:
    source = repo_root / file_name
    if source.is_file():
        datas.append((str(source), '.'))

block_cipher = None

main_script = repo_root / "main.py"

a = Analysis(
    [str(main_script)],
    pathex=[str(repo_root)],
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
    icon=icon_path,
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
