import db


def test_db_module_imports():
    assert hasattr(db, "DB")
