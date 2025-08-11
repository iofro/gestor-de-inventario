import os
from db import DB

def test_db_file_removable(tmp_path):
    db_path = tmp_path / "test.sqlite"
    db = DB(str(db_path))
    db.conn.execute("PRAGMA foreign_keys=ON")
    db.close()
    os.remove(db_path)
    assert not db_path.exists()
