"""
Script 4 (v3) - Normalizar ingredientes en su propia tabla.

Por qué esta versión es mucho más rápida que la anterior:
  - La v1/v2 hacían "DELETE FROM ingredientes WHERE recipe_id = ?" antes
    de cada receta. Sin índice en recipe_id, cada DELETE escanea la tabla
    entera -- y esa tabla va creciendo con cada receta procesada, así que
    el script se vuelve cada vez más lento (podía tardar horas o directamente
    no terminar nunca en un tiempo razonable).
  - Esta versión vacía la tabla 'ingredientes' UNA sola vez al principio
    (ya que de todas formas se reprocesan todas las recetas), y crea el
    índice recién al FINAL (crearlo antes también frenaría los inserts).

No pide nada a internet: solo lee el raw_json que ya está guardado en
la tabla 'recetas'.
"""

import sqlite3
import json
from tqdm import tqdm

DB_PATH = "food_scraping.db"
CADA_CUANTO_COMMITEAR = 1000


def crear_tabla_ingredientes(conn):
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ingredientes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recipe_id INTEGER,
            orden INTEGER,
            quantity TEXT,
            texto_completo TEXT,
            nombre_ingrediente TEXT,
            seo_url TEXT
        )
    """)
    conn.commit()


def resolver_texto(ingrediente):
    texto = ingrediente.get("ingredText", "") or ""
    if ingrediente.get("link"):
        reemplazos = ingrediente.get("hyperlinkFoodTextList", {}) or {}
        for clave, valor in reemplazos.items():
            texto = texto.replace(f"${clave}$", valor.get("text", ""))
    texto = " ".join(texto.split())
    return texto


def sacar_nombre_canonico(ingrediente):
    if not ingrediente.get("link"):
        return None, None
    reemplazos = ingrediente.get("hyperlinkFoodTextList", {}) or {}
    for valor in reemplazos.values():
        return valor.get("text"), valor.get("seoUrl")
    return None, None


def procesar_receta(cursor, recipe_id, raw_json_texto):
    try:
        receta = json.loads(raw_json_texto)
    except (json.JSONDecodeError, TypeError):
        return

    lista_ingredientes = receta.get("ingredients", []) or []

    for orden, ing in enumerate(lista_ingredientes, start=1):
        texto_completo = resolver_texto(ing)
        nombre, seo_url = sacar_nombre_canonico(ing)
        quantity = (ing.get("quantity") or "").strip()

        cursor.execute("""
            INSERT INTO ingredientes (recipe_id, orden, quantity, texto_completo, nombre_ingrediente, seo_url)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (recipe_id, orden, quantity, texto_completo, nombre, seo_url))


def main():
    conn = sqlite3.connect(DB_PATH)
    crear_tabla_ingredientes(conn)
    cursor = conn.cursor()

    # Vaciamos la tabla UNA sola vez (mucho más rápido que borrar receta
    # por receta), ya que de todas formas vamos a reprocesar todo.
    print("Vaciando tabla 'ingredientes' para reconstruirla desde cero...")
    cursor.execute("DELETE FROM ingredientes")
    conn.commit()

    cursor.execute("SELECT id, raw_json FROM recetas WHERE raw_json IS NOT NULL")
    filas = cursor.fetchall()
    print(f"Procesando ingredientes de {len(filas)} recetas...")

    for i, (recipe_id, raw_json_texto) in enumerate(tqdm(filas), start=1):
        procesar_receta(cursor, recipe_id, raw_json_texto)
        if i % CADA_CUANTO_COMMITEAR == 0:
            conn.commit()

    conn.commit()

    # Recién ahora creamos el índice, al final, sobre la tabla ya completa
    print("Creando índice en recipe_id...")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ingredientes_recipe_id ON ingredientes(recipe_id)")
    conn.commit()

    conn.close()
    print("Listo. Tabla 'ingredientes' reconstruida e indexada.")


if __name__ == "__main__":
    main()
