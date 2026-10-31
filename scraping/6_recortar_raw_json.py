"""
Script 6 (v3) - Recortar raw_json y compactar la base, POR TANDAS.

Por qué esta versión evita el problema de memoria de la v2:
  - La v2 podía terminar cargando en la RAM varios GB de raw_json de
    golpe (298.000 filas a la vez, sea por el modo Python de respaldo,
    o por el peso temporal de un UPDATE gigante en una sola transacción).
  - Esta versión procesa las recetas en TANDAS (por defecto 2000 a la
    vez), recorriendo rangos de id, y hace un commit después de cada
    tanda. Nunca tiene en memoria más que una tanda chica.
  - También fuerza a SQLite a usar el DISCO (no la RAM) como
    almacenamiento temporal durante el VACUUM (PRAGMA temp_store = FILE).
  - Es resumible: si se corta a mitad de camino, al volver a correrlo
    salta las recetas que ya fueron procesadas (no repite trabajo).

IMPORTANTE antes de correr esto:
  - Cerrá DBeaver (o cualquier otro programa) que tenga food_scraping.db
    abierto.
  - El VACUUM final sí necesita varios GB de espacio LIBRE EN DISCO
    (no RAM) porque reescribe el archivo entero -- eso no cambia por
    hacer el resto en tandas. Si el problema que tuviste fue de espacio
    en disco y no de RAM, avisame antes de correr esto.
"""

import sqlite3
import json
import os
from tqdm import tqdm

DB_PATH = "food_scraping.db"
TAMANIO_CHUNK = 2000  # recetas procesadas por tanda

COLUMNAS_NUEVAS = [
    ("author_recipes_count", "INTEGER"),
    ("author_follow_count", "INTEGER"),
    ("primary_image_url", "TEXT"),
    ("other_images_json", "TEXT"),
]


def columna_existe(cursor, tabla, columna):
    cursor.execute(f"PRAGMA table_info({tabla})")
    columnas = [fila[1] for fila in cursor.fetchall()]
    return columna in columnas


def agregar_columnas_si_faltan(conn):
    cursor = conn.cursor()
    for nombre, tipo in COLUMNAS_NUEVAS:
        if not columna_existe(cursor, "recetas", nombre):
            cursor.execute(f"ALTER TABLE recetas ADD COLUMN {nombre} {tipo}")
    conn.commit()


def tiene_json1(conn):
    try:
        conn.execute('SELECT json_extract(\'{"a":1}\', \'$.a\')')
        return True
    except sqlite3.OperationalError:
        return False


def rango_de_ids_pendientes(conn):
    cursor = conn.cursor()
    cursor.execute("""
        SELECT MIN(id), MAX(id) FROM recetas
        WHERE raw_json IS NOT NULL AND primary_image_url IS NULL
    """)
    return cursor.fetchone()


def rescatar_por_chunks_sql(conn):
    id_min, id_max = rango_de_ids_pendientes(conn)
    if id_min is None:
        print("No hay recetas pendientes de rescatar (ya se hizo, o no hay raw_json).")
        return

    cursor = conn.cursor()
    total_chunks = (id_max - id_min) // TAMANIO_CHUNK + 1
    print(f"Rescatando datos por tandas de {TAMANIO_CHUNK} (SQL), entre id {id_min} y {id_max}...")

    for inicio in tqdm(range(id_min, id_max + 1, TAMANIO_CHUNK), total=total_chunks):
        fin = inicio + TAMANIO_CHUNK - 1
        cursor.execute("""
            UPDATE recetas
            SET author_recipes_count = json_extract(raw_json, '$.contributor.recipesCount'),
                author_follow_count = json_extract(raw_json, '$.contributor.followMeCount'),
                primary_image_url = json_extract(raw_json, '$.primaryImage.defaultUrl'),
                other_images_json = (
                    SELECT json_group_array(json_extract(value, '$.defaultUrl'))
                    FROM json_each(raw_json, '$.otherImages')
                )
            WHERE id BETWEEN ? AND ?
              AND raw_json IS NOT NULL
              AND primary_image_url IS NULL
        """, (inicio, fin))
        conn.commit()

    print("Datos rescatados por tandas (SQL).")


def rescatar_por_chunks_python(conn):
    id_min, id_max = rango_de_ids_pendientes(conn)
    if id_min is None:
        print("No hay recetas pendientes de rescatar.")
        return

    cursor = conn.cursor()
    total_chunks = (id_max - id_min) // TAMANIO_CHUNK + 1
    print(f"Rescatando datos por tandas de {TAMANIO_CHUNK} (modo Python), entre id {id_min} y {id_max}...")

    for inicio in tqdm(range(id_min, id_max + 1, TAMANIO_CHUNK), total=total_chunks):
        fin = inicio + TAMANIO_CHUNK - 1
        cursor.execute("""
            SELECT id, raw_json FROM recetas
            WHERE id BETWEEN ? AND ?
              AND raw_json IS NOT NULL
              AND primary_image_url IS NULL
        """, (inicio, fin))
        filas = cursor.fetchall()  # como mucho TAMANIO_CHUNK filas en memoria, no 298.000

        for recipe_id, raw_json_texto in filas:
            try:
                receta = json.loads(raw_json_texto)
            except (json.JSONDecodeError, TypeError):
                continue

            contributor = receta.get("contributor", {}) or {}
            primary_image = receta.get("primaryImage", {}) or {}
            other_images = receta.get("otherImages", []) or []
            other_images_urls = [img.get("defaultUrl") for img in other_images if img.get("defaultUrl")]

            cursor.execute("""
                UPDATE recetas
                SET author_recipes_count = ?, author_follow_count = ?,
                    primary_image_url = ?, other_images_json = ?
                WHERE id = ?
            """, (
                contributor.get("recipesCount"),
                contributor.get("followMeCount"),
                primary_image.get("defaultUrl"),
                json.dumps(other_images_urls),
                recipe_id,
            ))

        conn.commit()

    print("Datos rescatados por tandas (Python).")


def vaciar_raw_json_por_chunks(conn):
    cursor = conn.cursor()
    cursor.execute("SELECT MIN(id), MAX(id) FROM recetas WHERE raw_json IS NOT NULL")
    id_min, id_max = cursor.fetchone()

    if id_min is None:
        print("raw_json ya estaba vacío en todas las filas.")
        return

    total_chunks = (id_max - id_min) // TAMANIO_CHUNK + 1
    print("Vaciando la columna raw_json por tandas...")

    for inicio in tqdm(range(id_min, id_max + 1, TAMANIO_CHUNK), total=total_chunks):
        fin = inicio + TAMANIO_CHUNK - 1
        cursor.execute("""
            UPDATE recetas SET raw_json = NULL
            WHERE id BETWEEN ? AND ? AND raw_json IS NOT NULL
        """, (inicio, fin))
        conn.commit()

    print("Columna raw_json vaciada.")


def compactar(conn):
    print("Configurando SQLite para usar disco (no RAM) como almacenamiento temporal...")
    conn.execute("PRAGMA temp_store = FILE")
    print("Corriendo VACUUM (puede tardar varios minutos, no lo interrumpas)...")
    conn.execute("VACUUM")
    print("VACUUM completo.")


def main():
    tamanio_antes = os.path.getsize(DB_PATH)
    print(f"Tamaño antes: {tamanio_antes / (1024**3):.2f} GB")

    conn = sqlite3.connect(DB_PATH)
    agregar_columnas_si_faltan(conn)

    if tiene_json1(conn):
        rescatar_por_chunks_sql(conn)
    else:
        rescatar_por_chunks_python(conn)

    cursor = conn.cursor()
    cursor.execute("""
        SELECT title, primary_image_url FROM recetas
        WHERE primary_image_url IS NOT NULL LIMIT 3
    """)
    print("\nMuestra de URLs rescatadas (chequeá que tengan sentido antes de seguir):")
    for title, url in cursor.fetchall():
        print(f"  {title} -> {url}")

    vaciar_raw_json_por_chunks(conn)
    compactar(conn)

    conn.close()

    tamanio_despues = os.path.getsize(DB_PATH)
    print(f"\nTamaño antes:   {tamanio_antes / (1024**3):.2f} GB")
    print(f"Tamaño después: {tamanio_despues / (1024**3):.2f} GB")
    print(f"Ahorrado: {(tamanio_antes - tamanio_despues) / (1024**3):.2f} GB")


if __name__ == "__main__":
    main()
