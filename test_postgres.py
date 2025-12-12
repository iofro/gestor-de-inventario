import psycopg
from psycopg.rows import dict_row


def main():
    # Ajusta estos parámetros a tu instalación local.
    conn = psycopg.connect(
        host="localhost",
        port=5432,
        dbname="VertexDte",
        user="postgres",
        password="5pollitos",
        row_factory=dict_row,
    )

    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS prueba (
                id SERIAL PRIMARY KEY,
                nombre TEXT NOT NULL
            )
            """
        )
        cur.execute(
            "INSERT INTO prueba (nombre) VALUES (%s) RETURNING id",
            ("Hola PostgreSQL",),
        )
        nuevo_id = cur.fetchone()["id"]
        conn.commit()

        cur.execute("SELECT * FROM prueba WHERE id = %s", (nuevo_id,))
        print(cur.fetchone())

    conn.close()


if __name__ == "__main__":
    main()
