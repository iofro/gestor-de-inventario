import os
import sys
import time
import gc
import sqlite3

import pytest

try:
    from PyQt5.QtWidgets import QApplication
except ImportError:  # pragma: no cover - PyQt5 may be missing in CI
    class QApplication:  # minimal stub for tests that don't use the GUI
        def __init__(self, *args, **kwargs):
            pass

        @staticmethod
        def instance():
            return None

from db import DB


@pytest.fixture(scope="function")
def db_conn(tmp_path):
    """Provide a temporary database connection for tests.

    The database lives in ``tmp_path`` and enforces foreign key constraints.
    After the test the database is aggressively cleaned up so the file can be
    removed even on platforms that keep file handles open briefly (e.g.
    Windows).
    """

    db_path = tmp_path / "test.sqlite"
    db = DB(str(db_path))
    db.conn.execute("PRAGMA foreign_keys=ON")
    # Expose path for tests that want to assert cleanup
    db.db_path = db_path

    yield db

    # Ensure cursors are closed and checkpoints run so SQLite releases locks
    try:
        db.cursor.close()
    except (AttributeError, sqlite3.Error):
        pass
    try:
        db.conn.execute("PRAGMA wal_checkpoint(FULL)")
        db.conn.execute("PRAGMA journal_mode=DELETE")
    except sqlite3.Error:
        pass
    try:
        db.conn.close()
    except sqlite3.Error:
        pass

    gc.collect()

    # Retry removing the database file a few times (helps on Windows)
    for _ in range(10):
        try:
            if db_path.exists():
                os.remove(db_path)
            break
        except OSError:
            time.sleep(0.1)


@pytest.fixture(scope="session")
def qt_app():
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    return QApplication.instance() or QApplication(sys.argv)
