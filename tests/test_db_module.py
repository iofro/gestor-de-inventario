import threading
from db import DB


def test_ensure_column_creation(monkeypatch, tmp_path):
    db = DB(str(tmp_path / 'db.sqlite'))
    db.cursor.execute('CREATE TABLE t(id INTEGER)')
    db.conn.commit()
    monkeypatch.setattr('builtins.input', lambda prompt: 's')
    assert db.ensure_column('t', 'name', 'TEXT')
    db.cursor.execute('PRAGMA table_info(t)')
    cols = [r[1] for r in db.cursor.fetchall()]
    assert 'name' in cols


def test_ensure_column_decline(monkeypatch, tmp_path):
    db = DB(str(tmp_path / 'db.sqlite'))
    db.cursor.execute('CREATE TABLE t(id INTEGER)')
    db.conn.commit()
    monkeypatch.setattr('builtins.input', lambda prompt: 'n')
    assert not db.ensure_column('t', 'name', 'TEXT')


def test_concurrent_access(tmp_path):
    db_path = str(tmp_path / 'db.sqlite')
    def worker(code):
        d = DB(db_path)
        d.add_cliente(f'c{code}', '', '', '', '', '', '', '', '', '')
    threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    d = DB(db_path)
    assert len(d.get_clientes()) == 2
