# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, collect_data_files
import certifi, os
import sys
from PyInstaller.building.datastruct import TOC, Tree

icon_path = 'assets/app.ico'
if not os.path.isfile(icon_path):
    icon_path = None

hidden = []
hidden += collect_submodules('PyQt5')
hidden += ['PyQt5.QtPrintSupport', 'PyQt5.QtSvg']
# 🔒 ReportLab: incluir todos los submódulos de barcode
hidden += collect_submodules('reportlab.graphics.barcode')
hidden = sorted(set(hidden))

datas = []
datas += collect_data_files('PyQt5', include_py_files=False)
# 🔒 ReportLab: añadir data files (fuentes/recursos)
datas += collect_data_files('reportlab', include_py_files=False)
# Certificados TLS para requests/httpx
datas += [(certifi.where(), 'certifi')]

spec_path = Path(locals().get('__file__', sys.argv[0])).resolve()
repo_root = spec_path.parent.parent

resource_directories = []
# 🔒 Incluye extras (firmador) y tus carpetas de recursos
for folder in [
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
    'schema_patches',
    'svfe-json-schemas',
    'tickets',
    'extras',
]:
    folder_path = Path(folder)
    if os.path.isdir(folder_path):
        resource_directories.append(folder_path)

for pattern in ['facturas_*', 'notas_*']:
    for match in repo_root.glob(pattern):
        if match.is_dir():
            resource_directories.append(match.relative_to(repo_root))

extra_datas = []
existing_directories = []

for directory in resource_directories:
    source_path = repo_root / directory
    if source_path.is_dir():
        datas.append((str(source_path), str(directory)))
        extra_datas.append(Tree(str(source_path), prefix=str(directory)))
        existing_directories.append(str(directory))

resource_files = [
    'style.qss',
    'logoinventario.jpg',
    'formato_factura.json',
    'datos_negocio.json',
    'config_negocio.json',
    'inventario.json',
    'VERSION',
    'avatar.jpg',

]

existing_files = []

for file_name in resource_files:
    source_path = repo_root / file_name
    if source_path.is_file():
        datas.append((str(source_path), '.'))
        extra_datas.append(TOC([(file_name, str(source_path), 'DATA')]))
        existing_files.append(file_name)

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

def _should_keep_data(entry: tuple[str, str, str]) -> bool:
    dest_name = entry[0]
    for directory in existing_directories:
        if dest_name == directory or dest_name.startswith(f"{directory}/"):
            return False
    return dest_name not in existing_files

a.datas = TOC([entry for entry in a.datas if _should_keep_data(entry)])
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
    contents_directory='.',
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    *extra_datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='VertexDTE',
)
