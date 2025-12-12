Cómo instalar PostgreSQL y crear una base de datos para tu aplicación

Este documento es una guía paso a paso para instalar PostgreSQL en una computadora nueva, configurarlo correctamente y probar la conexión desde Python.
Puedes guardarlo en un archivo .txt o .md como documentación permanente.

GUÍA COMPLETA PARA INSTALAR Y CONFIGURAR POSTGRESQL EN WINDOWS
PASO 1 — Descargar PostgreSQL

Ir al sitio oficial:
https://www.postgresql.org/download/

Elegir Windows.

Descargar el instalador recomendado (por ejemplo: PostgreSQL 18.1 Windows x86-64).

PASO 2 — Instalar PostgreSQL

Al ejecutar el instalador:

Dejar todo por defecto (ruta de instalación, componentes, etc.).

Cuando pida la contraseña para el usuario administrador postgres, escribir una contraseña segura.
En el ejemplo usamos:

5pollitos


Puerto: dejar 5432 (el estándar).

No es necesario marcar Stack Builder → desmarcar y finalizar.

PASO 3 — Abrir pgAdmin

pgAdmin es la herramienta gráfica que permite ver y administrar la base de datos.

Buscar en el menú Inicio: pgAdmin 4.

La primera vez pedirá la contraseña del usuario postgres.
Es la misma que se puso durante la instalación.
Ejemplo: 5pollitos.

PASO 4 — Conectarse al servidor desde pgAdmin

Si aparece un servidor ya listado, simplemente hacer doble clic y poner la contraseña.

Si no aparece:

Clic en Add New Server.

En General → Name:

PostgreSQL


En Connection:

Host: localhost

Port: 5432

Username: postgres

Password: 5pollitos

Marcar Save Password.

Guardar.

Luego debería aparecer:

Servers
 └── PostgreSQL
      ├── Databases
      └── Login/Group Roles

PASO 5 — Crear la base de datos del sistema

En pgAdmin, expandir:

Servers → PostgreSQL → Databases


Clic derecho en Databases.

Seleccionar Create → Database…

Nombre de la base:

VertexDte


Owner: postgres.

Guardar.

La base ya está creada y vacía.

PASO 6 — Instalar el driver PostgreSQL para Python

En una terminal PowerShell (o CMD), dentro del entorno virtual de Python:

py -m pip install "psycopg[binary]"


O si eso falla:

py -m pip install psycopg2-binary


Esto instala el driver que permite que Python se conecte a PostgreSQL.

PASO 7 — Crear un script de prueba en Python

Crear un archivo test_postgres.py con esto:

import psycopg
from psycopg.rows import dict_row

def main():
    conn = psycopg.connect(
        host="localhost",
        port=5432,
        dbname="VertexDte",      # nombre de la base creada
        user="postgres",
        password="5pollitos",    # contraseña definida en instalación
        row_factory=dict_row,
    )

    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS prueba (
                id SERIAL PRIMARY KEY,
                nombre TEXT NOT NULL
            )
        """)

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

PASO 8 — Ejecutar el script de prueba

Entrar a la carpeta del proyecto y activar el entorno virtual:

.\.venv\Scripts\Activate.ps1


Luego ejecutar:

python test_postgres.py


Si todo funciona, debe imprimir:

{'id': 1, 'nombre': 'Hola PostgreSQL'}


Esto confirma que:

PostgreSQL funciona

La base VertexDte existe

La contraseña es correcta

Python se conectó correctamente

Se pueden insertar y leer datos

PASO 9 — El sistema ya está listo para usar PostgreSQL

Una vez que este test funciona, se puede migrar tu db.py para que tu aplicación use PostgreSQL en lugar de SQLite.

Este fue el tutorial completo.

Puedes guardarlo tal cual en un archivo .txt o .md como referencia permanente.
