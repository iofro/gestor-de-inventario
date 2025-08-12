# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file for barcode_example.py.

The key part is the ``hiddenimports`` definition which ensures that all
ReportLab barcode submodules (e.g., Code128, QR) are bundled into the
executable.  Without these, running the frozen app would raise
``ModuleNotFoundError`` for the barcode modules because ReportLab loads
them dynamically.
"""

from PyInstaller.utils.hooks import collect_submodules

# Collect every submodule under reportlab.graphics.barcode so PyInstaller
# includes them in the build. This covers Code128, QR, and any other
# barcode implementations provided by ReportLab.
hidden_imports = collect_submodules("reportlab.graphics.barcode")

block_cipher = None


a = Analysis(
    ["barcode_example.py"],
    pathex=["."],
    binaries=[],
    datas=[],
    hiddenimports=hidden_imports,
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
    [],
    exclude_binaries=True,
    name="barcode_example",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="barcode_example",
)
