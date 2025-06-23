import sqlite3
import sys

def main(db_path):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    try:
        c.execute("PRAGMA foreign_keys=off")
        c.execute("BEGIN")
        # Check if column exists
        c.execute("PRAGMA table_info(ventas_credito_fiscal)")
        cols = [row[1] for row in c.fetchall()]
        if 'iva_retenido' in cols:
            columns_without = [col for col in cols if col != 'iva_retenido']
            col_list = ','.join(columns_without)
            c.execute(f"CREATE TABLE IF NOT EXISTS ventas_credito_fiscal_tmp AS SELECT {col_list} FROM ventas_credito_fiscal")
            c.execute("DROP TABLE ventas_credito_fiscal")
            c.execute(f"ALTER TABLE ventas_credito_fiscal_tmp RENAME TO ventas_credito_fiscal")
        conn.commit()
    finally:
        conn.close()

if __name__ == '__main__':
    if len(sys.argv) != 2:
        print('Usage: python remove_iva_retenido_column.py <database>')
        sys.exit(1)
    main(sys.argv[1])
