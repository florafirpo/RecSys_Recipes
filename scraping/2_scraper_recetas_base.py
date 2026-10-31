"""
Script A - Pasada base (liviana): UN pedido /as-json por receta.

De ese único pedido sacamos:
  - Datos de la receta (título, descripción, ingredientes, pasos, nutrición)
  - rating.value y rating.count -> esto nos dice qué tan "interactuada" es la receta
  - Los primeros comentarios, que YA vienen incluidos en reviewFeed.data.items
  - Datos del autor de la receta (bio, ubicación) sin visitar su perfil aparte

Si reviewFeed.total > 5, esa receta queda marcada como "le faltan comentarios"
(columna faltan_comentarios = 1) para que el Script B la complete después,
empezando por las que tienen más interacción.
"""

import requests
import sqlite3
import time
import json
import csv
import random
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
DB_PATH = "food_scraping.db"
CSV_URLS = "recetas_urls.csv"

MAX_WORKERS = 3
PAUSA_MIN = 1.2              # segundos, límite inferior de la pausa random
PAUSA_MAX = 2.5              # segundos, límite superior
MAX_REINTENTOS = 2

# --- Circuit breaker: si el sitio nos empieza a bloquear, frenamos SOLO,
# en vez de seguir insistiendo y empeorar el bloqueo ---
BLOQUEOS_PARA_FRENAR = 5     # si se acumulan 5 bloqueos seguidos, se corta
bloqueos_consecutivos = 0
lock_bloqueos = threading.Lock()
evento_detener = threading.Event()


def crear_tablas(conn):
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS recetas (
            id INTEGER PRIMARY KEY,
            url TEXT UNIQUE,
            title TEXT,
            description TEXT,
            category TEXT,
            rating_value REAL,
            rating_count INTEGER,
            author_id INTEGER,
            author_name TEXT,
            author_bio TEXT,
            author_location TEXT,
            ingredients_json TEXT,
            directions_json TEXT,
            nutrition_json TEXT,
            raw_json TEXT,
            total_comentarios INTEGER,
            faltan_comentarios INTEGER DEFAULT 0,
            scraped_ok INTEGER DEFAULT 0
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS comentarios (
            id INTEGER PRIMARY KEY,
            recipe_id INTEGER,
            member_id INTEGER,
            member_name TEXT,
            rating INTEGER,
            text TEXT,
            submitted TEXT,
            likes INTEGER
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS errores (
            url TEXT,
            motivo TEXT,
            fecha TEXT
        )
    """)
    conn.commit()


def cargar_urls_iniciales(conn):
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM recetas")
    if cursor.fetchone()[0] > 0:
        print("Las URLs ya estaban cargadas, no vuelvo a leer el CSV.")
        return

    print("Cargando URLs del CSV...")
    with open(CSV_URLS, encoding="utf-8") as f:
        urls = [fila["url_receta"] for fila in csv.DictReader(f)]

    cursor.executemany(
        "INSERT OR IGNORE INTO recetas (url, scraped_ok) VALUES (?, 0)",
        [(u,) for u in urls]
    )
    conn.commit()
    print(f"Cargadas {len(urls)} URLs.")


def pedido_con_reintentos(url):
    global bloqueos_consecutivos

    for _ in range(MAX_REINTENTOS + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)

            if r.status_code == 200:
                # pedido OK, reseteamos el contador de bloqueos
                with lock_bloqueos:
                    bloqueos_consecutivos = 0
                return r.json()

            if r.status_code in (403, 429):
                # esto es un bloqueo, no un error cualquiera
                with lock_bloqueos:
                    bloqueos_consecutivos += 1
                    if bloqueos_consecutivos >= BLOQUEOS_PARA_FRENAR:
                        evento_detener.set()
                raise BloqueoDetectado(r.status_code)

            return None  # otro tipo de error HTTP, no reintentamos mucho

        except requests.exceptions.RequestException:
            time.sleep(1)
    return None


class BloqueoDetectado(Exception):
    def __init__(self, status_code):
        self.status_code = status_code
        super().__init__(f"Bloqueado por el servidor (HTTP {status_code})")


def procesar_receta(url):
    if evento_detener.is_set():
        return {"url": url, "ok": False, "motivo": "detenido por bloqueo, no se llegó a pedir"}

    try:
        time.sleep(random.uniform(PAUSA_MIN, PAUSA_MAX))
        data = pedido_con_reintentos(url.rstrip("/") + "/as-json")

        if data is None or "recipe" not in data:
            return {"url": url, "ok": False, "motivo": "sin as-json"}

        receta = data["recipe"]
        review_feed = data.get("reviewFeed", {})
        total_reviews = review_feed.get("total", 0)
        comentarios = review_feed.get("data", {}).get("items", [])

        return {
            "url": url,
            "ok": True,
            "receta": receta,
            "total_reviews": total_reviews,
            "comentarios": comentarios,
        }
    except Exception as e:
        return {"url": url, "ok": False, "motivo": str(e)}


def guardar_resultado(conn, resultado):
    cursor = conn.cursor()

    if not resultado["ok"]:
        cursor.execute(
            "INSERT INTO errores (url, motivo, fecha) VALUES (?, ?, datetime('now'))",
            (resultado["url"], resultado.get("motivo", "desconocido"))
        )
        conn.commit()
        return

    receta = resultado["receta"]
    comentarios = resultado["comentarios"]
    total_reviews = resultado["total_reviews"]
    autor = receta.get("author", {}) or {}
    rating = receta.get("rating", {}) or {}

    faltan = 1 if total_reviews > len(comentarios) else 0

    cursor.execute("""
        UPDATE recetas
        SET title = ?, description = ?, category = ?,
            rating_value = ?, rating_count = ?,
            author_id = ?, author_name = ?, author_bio = ?, author_location = ?,
            ingredients_json = ?, directions_json = ?, nutrition_json = ?,
            raw_json = ?, total_comentarios = ?, faltan_comentarios = ?, scraped_ok = 1
        WHERE url = ?
    """, (
        receta.get("title"),
        receta.get("description"),
        (receta.get("category") or {}).get("name"),
        rating.get("value"),
        rating.get("count"),
        autor.get("id"),
        autor.get("name"),
        autor.get("bio"),
        autor.get("location"),
        json.dumps(receta.get("ingredients")),
        json.dumps(receta.get("directions")),
        json.dumps(receta.get("nutrition")),
        json.dumps(receta),
        total_reviews,
        faltan,
        resultado["url"],
    ))

    recipe_id = receta.get("id")

    for c in comentarios:
        cursor.execute("""
            INSERT OR IGNORE INTO comentarios
            (id, recipe_id, member_id, member_name, rating, text, submitted, likes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            c.get("id"), recipe_id, c.get("memberId"), c.get("memberName"),
            c.get("rating"), c.get("text"), c.get("submitted"),
            c.get("counts", {}).get("like"),
        ))

    conn.commit()


def main(limite=None):
    conn = sqlite3.connect(DB_PATH)
    crear_tablas(conn)
    cargar_urls_iniciales(conn)

    cursor = conn.cursor()
    cursor.execute("SELECT url FROM recetas WHERE scraped_ok = 0")
    urls_pendientes = [fila[0] for fila in cursor.fetchall()]

    if limite:
        urls_pendientes = urls_pendientes[:limite]

    print(f"Recetas a procesar en esta corrida: {len(urls_pendientes)}")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futuros = {executor.submit(procesar_receta, url): url for url in urls_pendientes}

        for futuro in tqdm(as_completed(futuros), total=len(urls_pendientes)):
            guardar_resultado(conn, futuro.result())

            if evento_detener.is_set():
                # cancelamos las tareas que todavía no arrancaron
                for f in futuros:
                    f.cancel()
                break

    conn.close()

    if evento_detener.is_set():
        print("\n⚠️  CORTADO: el sitio empezó a devolver bloqueos (403/429) varias veces seguidas.")
        print("No sigas corriendo el script ahora mismo — esperá unas horas (o hasta mañana)")
        print("antes de reintentar, para no extender el bloqueo. Cuando retomes, el script")
        print("va a seguir exactamente donde quedó, gracias a scraped_ok.")
    else:
        print("Listo esta tanda.")


if __name__ == "__main__":
    # Probar primero con pocas:
    #main(limite=10)
    # Cuando confirmes que anduvo bien, para la corrida completa:
    main()
