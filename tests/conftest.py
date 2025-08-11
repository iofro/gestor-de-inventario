import os
import sys
import time
import gc

import pytest
from PyQt5.QtWidgets import QApplication

from db import DB


@pytest.fixture(scope="function")
def db_conn(tmp_path):
    db_path = tmp_path / "test.sqlite"
    db = DB(str(db_path))
    db.conn.execute("PRAGMA foreign_keys=ON")
    yield db
    # Cerrar cursores conocidos
    try:
        try:
            db.cursor.close()
        except Exception:
            pass
        # Forzar checkpoint WAL y volver a DELETE para liberar locks
        try:
            db.conn.execute("PRAGMA wal_checkpoint(FULL)")
            db.conn.execute("PRAGMA journal_mode=DELETE")
        except Exception:
            pass
    finally:
        try:
            db.conn.close()
        except Exception:
            pass

    # Forzar GC para soltar handles colgantes
    gc.collect()

    # Reintentar borrar el archivo en Windows
    for _ in range(10):
        try:
            if db_path.exists():
                os.remove(db_path)
            break
        except PermissionError:
            time.sleep(0.2)
    else:
        print(f"WARNING: could not delete {db_path} (locked)")


@pytest.fixture(scope="session")
def qt_app():
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    return QApplication.instance() or QApplication(sys.argv)
