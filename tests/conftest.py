import os
import sys

import pytest
from PyQt5.QtWidgets import QApplication

from db import DB

@pytest.fixture(scope="function")
def db_conn(tmp_path):
    """Provide a fresh database connection for each test.

    The database is created in a temporary location with foreign key
    enforcement enabled. Schema setup and migrations run as part of ``DB``
    initialization. The database file is removed after each test to ensure a
    clean state.
    """
    db_path = tmp_path / "test.sqlite"
    db = DB(str(db_path))
    db.conn.execute("PRAGMA foreign_keys=ON")
    yield db
    db.conn.close()
    if db_path.exists():
        os.remove(db_path)


@pytest.fixture(scope="session")
def qt_app():
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    return QApplication.instance() or QApplication(sys.argv)
