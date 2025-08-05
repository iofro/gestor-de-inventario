"""Script to add missing indexes to existing ``inventario.db`` databases.

This script creates the following indexes on the ``productos`` table if they do
not already exist:

* ``productos(vendedor_id)``
* ``productos(Distribuidor_id)``
* ``productos(codigo)``
* ``productos(nombre)``

Run the script with ``python add_product_indexes.py``. The script uses the same
database location as the application (`inventario.db` in the repository root).
"""

from db import DB


def main() -> None:
    """Ensure required indexes exist on the ``productos`` table."""
    db = DB()  # DB.__init__ already runs ``setup`` which creates the indexes.
    db.conn.commit()
    print("Índices de productos verificados/creados correctamente.")


if __name__ == "__main__":
    main()

