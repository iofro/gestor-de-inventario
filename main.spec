# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_submodules
from PyInstaller.building.datastruct import Tree

resource_trees = [
    Tree('schema_patches', prefix='schema_patches'),
    Tree('svfe-json-schemas', prefix='svfe-json-schemas'),
    Tree('templates', prefix='templates'),
]

# Collect all barcode submodules so ReportLab barcodes such as Code93 and
# Code128 are bundled with the executable.
hidden_imports = collect_submodules("reportlab.graphics.barcode")

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('avatar.jpg', '.'),
        ('logoinventario.jpg', '.'),
        ('style.qss', '.'),
        ('inventario.json', '.'),
        ('ultimo_inventario.json', '.'),
        ('formato_factura.json', '.'),
        ('datos_negocio.json', '.'),
        ('config_negocio.json', '.'),
        ('VERSION', '.'),
        ('schema_patches', 'schema_patches'),
        ('svfe-json-schemas', 'svfe-json-schemas'),
    ],
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
    *resource_trees,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='main',
)
