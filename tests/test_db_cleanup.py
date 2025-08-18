import os


def test_db_file_removable(db_conn):
    """The SQLite file can be removed after closing the connection."""

    db_path = db_conn.db_path
    db_conn.close()
    os.remove(db_path)
    assert not db_path.exists()
