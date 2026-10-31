"""
Script 5 - Resumen final de la base food_scraping.db

Da un panorama completo:
  - Cuántas recetas, comentarios, ingredientes hay
  - Cobertura de reseñas (clave para un sistema de recomendación: recetas
    sin interacción no sirven de nada para collaborative filtering)
  - Cuántos usuarios únicos aparecen (esto es lo que falta scrapear en la
    Fase 4, todavía no armamos la tabla 'usuarios')
  - Tamaño del archivo en disco
"""

import sqlite3
import os

DB_PATH = "food_scraping.db"


def seccion(titulo):
    print("\n" + "=" * 60)
    print(titulo)
    print("=" * 60)


def main():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # ---------- Tablas existentes ----------
    seccion("TABLAS EN LA BASE")
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tablas = [fila[0] for fila in cursor.fetchall()]
    print(", ".join(tablas))

    # ---------- Tamaño del archivo ----------
    seccion("ARCHIVO")
    tamanio_bytes = os.path.getsize(DB_PATH)
    print(f"food_scraping.db pesa: {tamanio_bytes / (1024**3):.2f} GB ({tamanio_bytes / (1024**2):.0f} MB)")

    # ---------- Recetas ----------
    seccion("RECETAS")
    cursor.execute("SELECT COUNT(*) FROM recetas")
    total_recetas = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM recetas WHERE scraped_ok = 1")
    scrapeadas = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM recetas WHERE faltan_comentarios = 1")
    faltan = cursor.fetchone()[0]

    print(f"Total de recetas cargadas:     {total_recetas}")
    if total_recetas:
        print(f"Recetas scrapeadas OK:          {scrapeadas} ({scrapeadas/total_recetas*100:.1f}%)")
    print(f"Recetas sin scrapear todavía:   {total_recetas - scrapeadas}")
    print(f"Recetas con reviews incompletas (>5, pendientes del Script 3): {faltan}")

    # ---------- Comentarios: cobertura para recomendación ----------
    seccion("COMENTARIOS / RESEÑAS")
    cursor.execute("SELECT COUNT(*) FROM comentarios")
    total_comentarios = cursor.fetchone()[0]
    print(f"Total de comentarios/reseñas guardados: {total_comentarios}")

    if scrapeadas > 0:
        print(f"Promedio de reseñas por receta (sobre scrapeadas): {total_comentarios/scrapeadas:.2f}")

    # Distribución: esto es LA pregunta clave para un sistema de recomendación.
    cursor.execute("""
        SELECT
            SUM(CASE WHEN total_comentarios = 0 THEN 1 ELSE 0 END) AS con_0,
            SUM(CASE WHEN total_comentarios BETWEEN 1 AND 4 THEN 1 ELSE 0 END) AS de_1_a_4,
            SUM(CASE WHEN total_comentarios BETWEEN 5 AND 19 THEN 1 ELSE 0 END) AS de_5_a_19,
            SUM(CASE WHEN total_comentarios BETWEEN 20 AND 49 THEN 1 ELSE 0 END) AS de_20_a_49,
            SUM(CASE WHEN total_comentarios >= 50 THEN 1 ELSE 0 END) AS de_50_mas
        FROM recetas
        WHERE scraped_ok = 1
    """)
    fila = cursor.fetchone()
    con_0, de_1_a_4, de_5_a_19, de_20_a_49, de_50_mas = [x or 0 for x in fila]

    print("\nDistribución de recetas según cantidad de reseñas (sobre recetas scrapeadas):")
    for etiqueta, cantidad in [
        ("0 reseñas", con_0),
        ("1-4 reseñas", de_1_a_4),
        ("5-19 reseñas", de_5_a_19),
        ("20-49 reseñas", de_20_a_49),
        ("50+ reseñas", de_50_mas),
    ]:
        pct = (cantidad / scrapeadas * 100) if scrapeadas else 0
        print(f"  {etiqueta:15s}: {cantidad:>7} recetas  ({pct:5.1f}%)")

    if scrapeadas:
        con_al_menos_1 = scrapeadas - con_0
        print(f"\n% de recetas con AL MENOS 1 reseña (útiles para collaborative filtering): "
              f"{con_al_menos_1/scrapeadas*100:.1f}%")

    # ---------- Usuarios únicos (todavía no scrapeados en detalle) ----------
    seccion("USUARIOS (pendiente Fase 4)")
    cursor.execute("SELECT COUNT(DISTINCT member_id) FROM comentarios WHERE member_id IS NOT NULL")
    usuarios_por_comentarios = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(DISTINCT author_id) FROM recetas WHERE author_id IS NOT NULL")
    usuarios_autores = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(DISTINCT member_id) FROM (
            SELECT member_id FROM comentarios WHERE member_id IS NOT NULL
            UNION
            SELECT author_id AS member_id FROM recetas WHERE author_id IS NOT NULL
        )
    """)
    usuarios_totales = cursor.fetchone()[0]

    print(f"Usuarios únicos que comentaron:        {usuarios_por_comentarios}")
    print(f"Usuarios únicos que subieron recetas:   {usuarios_autores}")
    print(f"Usuarios únicos en total (unión):       {usuarios_totales}")
    print("(Todavía no hay una tabla 'usuarios' con perfiles completos -- eso es la Fase 4 pendiente)")

    # ---------- Ingredientes ----------
    seccion("INGREDIENTES")
    if "ingredientes" in tablas:
        cursor.execute("SELECT COUNT(*) FROM ingredientes")
        total_ingredientes = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(DISTINCT nombre_ingrediente) FROM ingredientes WHERE nombre_ingrediente IS NOT NULL")
        ingredientes_unicos = cursor.fetchone()[0]
        print(f"Total filas en ingredientes:      {total_ingredientes}")
        print(f"Ingredientes únicos (con nombre canónico): {ingredientes_unicos}")
    else:
        print("Todavía no corriste el Script 4 (normalizar_ingredientes) -- no existe la tabla.")

    # ---------- Errores ----------
    seccion("ERRORES")
    cursor.execute("SELECT COUNT(*) FROM errores")
    total_errores = cursor.fetchone()[0]
    print(f"Total de errores registrados: {total_errores}")
    if total_errores > 0:
        cursor.execute("SELECT motivo, COUNT(*) FROM errores GROUP BY motivo ORDER BY COUNT(*) DESC LIMIT 10")
        print("Motivos más comunes:")
        for motivo, cantidad in cursor.fetchall():
            print(f"  {cantidad:>6}  {motivo}")

    # ---------- Rating ----------
    seccion("RATING")
    cursor.execute("SELECT AVG(rating_value), MIN(rating_value), MAX(rating_value) FROM recetas WHERE rating_value IS NOT NULL")
    prom, minimo, maximo = cursor.fetchone()
    if prom is not None:
        print(f"Rating promedio: {prom:.2f} (min {minimo}, max {maximo})")
    else:
        print("Sin datos de rating todavía.")

    conn.close()
    print("\n" + "=" * 60)
    print("Fin del resumen.")
    print("=" * 60)


if __name__ == "__main__":
    main()
