"""
Chequeo de progreso y calidad de datos.

Se puede correr en OTRA terminal mientras el scraper principal sigue
corriendo (SQLite permite leer aunque otro proceso esté escribiendo,
por eso el timeout más largo al conectar).
"""

import sqlite3

DB_PATH = "food_scraping.db"


def main():
    # timeout más largo por si la base está ocupada escribiendo justo en ese instante
    conn = sqlite3.connect(DB_PATH, timeout=30)
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM recetas")
    total = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM recetas WHERE scraped_ok = 1")
    scrapeadas = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM comentarios")
    total_comentarios = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM errores")
    total_errores = cursor.fetchone()[0]

    print(f"Recetas totales:      {total}")
    print(f"Recetas scrapeadas:   {scrapeadas} ({scrapeadas/total*100:.1f}%)")
    print(f"Recetas restantes:    {total - scrapeadas}")
    print(f"Comentarios bajados:  {total_comentarios}")
    print(f"Errores:              {total_errores}")

    if total_errores > 0:
        print("\nÚltimos 5 errores (para ver si hay un patrón, ej. muchos 'timeout' o 'sin as-json'):")
        cursor.execute("SELECT url, motivo, fecha FROM errores ORDER BY fecha DESC LIMIT 5")
        for url, motivo, fecha in cursor.fetchall():
            print(f"  [{fecha}] {motivo} -> {url}")

    print("\nMuestra de 3 recetas ya scrapeadas (para chequear que los datos vinieron bien):")
    cursor.execute("""
        SELECT title, rating_value, rating_count, total_comentarios
        FROM recetas
        WHERE scraped_ok = 1
        ORDER BY RANDOM()
        LIMIT 3
    """)
    for title, rating_value, rating_count, total_comentarios in cursor.fetchall():
        print(f"  - {title} | rating: {rating_value} ({rating_count} votos) | {total_comentarios} comentarios")

    conn.close()


if __name__ == "__main__":
    main()
