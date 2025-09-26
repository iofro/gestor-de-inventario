import os
import PyInstaller.__main__

SEP = ';' if os.name == 'nt' else ':'

PyInstaller.__main__.run([
    'main.py',
    '--name=InventarioFarmacia',
    '--onefile',                # Un solo ejecutable
    '--windowed',               # Sin consola (para apps gráficas)
    f'--add-data=db.py{SEP}.',       # Incluye db.py
    f'--add-data=dialogs.py{SEP}.',
    f'--add-data=inventory_manager.py{SEP}.',
    f'--add-data=factura_sv.py{SEP}.',
    f'--add-data=ui_mainwindow.py{SEP}.',
    f'--add-data=style.qss{SEP}.',
    f'--add-data=logoinventario.jpg{SEP}.',
    f'--add-data=inventario.json{SEP}.',
    f'--add-data=ultimo_inventario.json{SEP}.',
    f'--add-data=avatar.jpg{SEP}.',
    # Agrega aquí otros archivos necesarios (imágenes, .ui, etc.)
])

# Nota:
# Si usas imágenes, archivos .ui o recursos, agrega más líneas '--add-data=archivo;carpeta_destino'
# En Mac/Linux, usa ':' en vez de ';' como separador en --add-data