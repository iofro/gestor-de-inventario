# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_submodules, collect_data_files
from PyInstaller.building.datastruct import Tree
import certifi

resource_trees = [
    Tree('schema_patches', prefix='schema_patches'),
    Tree('svfe-json-schemas', prefix='svfe-json-schemas'),
]

# Hidden imports
hidden_imports = (
    collect_submodules("reportlab.graphics.barcode")
    + collect_submodules("openpyxl")
    + collect_submodules("PyQt5")
    + ["PyQt5.QtPrintSupport", "PyQt5.QtSvg"]
)
hidden_imports = sorted(set(hidden_imports))

datas = []
datas += collect_data_files("reportlab", include_py_files=False)
datas += collect_data_files("openpyxl", include_py_files=False)
datas += [(certifi.where(), "certifi")]
datas += [
    ('avatar.jpg', '.'),
    ('logoinventario.jpg', '.'),
    ('style.qss', '.'),
    ('inventario.json', '.'),
    ('ultimo_inventario.json', '.'),
    ('formato_factura.json', '.'),
    ('datos_negocio.json', '.'),
    ('config_negocio.json', '.'),
    ('VERSION', '.'),
]
datas += resource_trees

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='main',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='main',
)
