import PyInstaller.__main__

PyInstaller.__main__.run([
    'main.py',
    '--name=InventarioFarmacia',
    '--onefile',                # Un solo ejecutable
    '--windowed',               # Sin consola (para apps gráficas)
    '--add-data=db.py;.',       # Incluye db.py
    '--add-data=dialogs.py;.',
    '--add-data=inventory_manager.py;.',
    '--add-data=factura_sv.py;.',
    '--add-data=ui_mainwindow.py;.',
    '--add-data=inventario.db;.',  # Incluye la base de datos si ya existe
    # Agrega aquí otros archivos necesarios (imágenes, .ui, etc.)
])

# Nota:
# Si usas imágenes, archivos .ui o recursos, agrega más líneas '--add-data=archivo;carpeta_destino'
# En Mac/Linux, usa ':' en vez de ';' como separador en --add-data