# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_submodules, collect_all
from PyInstaller.building.datastruct import Tree
import certifi

reportlab_datas, reportlab_binaries, reportlab_hiddenimports = collect_all("reportlab")
openpyxl_datas, openpyxl_binaries, openpyxl_hiddenimports = collect_all("openpyxl")

resource_trees = [
    Tree('schema_patches', prefix='schema_patches'),
    Tree('svfe-json-schemas', prefix='svfe-json-schemas'),
]

# Hidden imports
hidden_imports = sorted(
    set(
        reportlab_hiddenimports
        + openpyxl_hiddenimports
        + collect_submodules("reportlab.graphics.barcode")
        + collect_submodules("PyQt5")
        + ["PyQt5.QtPrintSupport", "PyQt5.QtSvg"]
    )
)

datas = []
datas += reportlab_datas
datas += openpyxl_datas
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

binaries = []
binaries += reportlab_binaries
binaries += openpyxl_binaries

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
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
