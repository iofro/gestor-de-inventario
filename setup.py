import os
import PyInstaller.__main__

SEP = ';' if os.name == 'nt' else ':'

add_data = [
    f'db.py{SEP}.',
    f'dialogs.py{SEP}.',
    f'inventory_manager.py{SEP}.',
    f'factura_sv.py{SEP}.',
    f'ui_mainwindow.py{SEP}.',
    f'style.qss{SEP}.',
    f'logoinventario.jpg{SEP}.',
    f'inventario.json{SEP}.',
    f'ultimo_inventario.json{SEP}.',
    f'avatar.jpg{SEP}.',
    f'svfe-json-schemas{SEP}svfe-json-schemas',
    f'schema_patches{SEP}schema_patches',
    f'VERSION{SEP}.',
    f'datos_negocio.json{SEP}.',
    f'config_negocio.json{SEP}.',
    f'utils/catalogos{SEP}utils/catalogos',
]

PyInstaller.__main__.run([
    'main.py',
    '--name=InventarioFarmacia',
    '--onefile',                # Un solo ejecutable
    '--windowed',               # Sin consola (para apps gráficas)
    *[arg for item in add_data for arg in ('--add-data', item)],
])

# Nota:
# Si usas imágenes, archivos .ui o recursos, agrega más líneas '--add-data=archivo;carpeta_destino'
# En Mac/Linux, usa ':' en vez de ';' como separador en --add-data