"""
Script 3 (v2, corregido) - Completar los comentarios que faltan de cada receta.

QUE SE CORRIGIO RESPECTO DE LA v1:
  1. La v1 pedia <url>/reviews?pn=2, que no existe (HTTP 404). El endpoint real es
         https://api.food.com/external/v1/recipes/<id>/feed/reviews?pn=N&sort=-like
     y cada pagina trae 5 comentarios.
  2. La v1 trataba el 404 como "no hay mas paginas" y marcaba la receta como
     completa sin haber guardado nada (fallo silencioso). Ahora una receta solo
     se marca completa (faltan_comentarios = 0) si bajaron TODAS sus paginas.
     Si algo falla queda pendiente y se anota en la tabla 'errores'.
  3. La v1 guardaba con recetas.id (numero interno). Ahora se guarda con el id
     real de food.com (el numero al final de la URL), igual que el Script 2.

Uso:
  python 3_completar_comentarios.py --reset-marcas        (UNA vez: vuelve a poner como
                                               pendientes las recetas con mas de 5 reviews)
  python 3_completar_comentarios.py --limite 20           (prueba chica: 20 recetas)
  python 3_completar_comentarios.py --limite 2000 --min-reviews 15 --tope-paginas 10
  python 3_completar_comentarios.py --parciales --tope-paginas 20
        (retoma las recetas "parciales": sigue desde la ultima pagina bajada, sin repetir;
         con otro tope baja mas paginas, o sin --tope-paginas las completa del todo)
        (--tope-paginas 10 baja como maximo 10 paginas extra = 50 reviews mas por receta;
         las recetas topeadas quedan con faltan_comentarios = 2 = "parcial")
  python 3_completar_comentarios.py                       (todas las pendientes, de mas a menos reviews)

Se puede cortar con Ctrl+C y volver a correr: sigue donde quedo.
"""

import argparse
import math
import random
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from tqdm import tqdm

DB_PATH = "food_scraping.db"
API = "https://api.food.com/external/v1/recipes/{id}/feed/reviews"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Content-Type": "application/json",
    "Origin": "https://www.food.com",
    "Referer": "https://www.food.com/",
}
REVIEWS_POR_PAGINA = 5
PAUSA_MIN, PAUSA_MAX = 1.0, 2.5
MAX_REINTENTOS = 2
BLOQUEOS_PARA_FRENAR = 5
# Si se corta internet (wifi, la compu se suspendio), en vez de dar la receta por
# perdida enseguida, esperamos y reintentamos: 15 s, 30 s, 60 s, 120 s, 240 s, 300 s...
# (unos 15 minutos en total) antes de rendirnos.
ESPERAS_SIN_RED = [15, 30, 60, 120, 240, 300, 300]

bloqueos_consecutivos = 0
lock_bloqueos = threading.Lock()
evento_detener = threading.Event()

# Cada cuantas paginas se guardan los comentarios en la base. Antes se guardaba
# recien al terminar la receta entera: si se cortaba el script en una receta de
# 600 paginas, se perdia todo lo bajado de esa receta.
GUARDAR_CADA_PAGINAS = 10
lock_base = threading.Lock()   # un solo hilo escribe en la base a la vez
barra = None                   # barra de progreso por pedido (se crea en main)


def guardar_comentarios(db_path, food_id, items):
    """Inserta una tanda de comentarios y hace commit. Devuelve cuantos eran nuevos."""
    if not items:
        return 0
    with lock_base:
        con = sqlite3.connect(db_path, timeout=60)
        cur = con.cursor()
        nuevos = 0
        for c in items:
            cur.execute("""
                INSERT OR IGNORE INTO comentarios
                (id, recipe_id, member_id, member_name, rating, text, submitted, likes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (c.get("id"), food_id, c.get("memberId"), c.get("memberName"),
                  c.get("rating"), c.get("text"), c.get("submitted"),
                  (c.get("counts") or {}).get("like")))
            nuevos += cur.rowcount
        con.commit()
        con.close()
    return nuevos


class BloqueoDetectado(Exception):
    pass


def id_food_desde_url(url):
    if not url:
        return None
    ultimo = url.rstrip("/").rsplit("-", 1)[-1]
    return int(ultimo) if ultimo.isdigit() else None


def pedir_pagina(food_id, pn):
    """Devuelve (items, total). Lanza excepcion si no pudo: nunca devuelve 'vacio' por un error."""
    global bloqueos_consecutivos
    ultimo_error = "sin respuesta"
    cortes_de_red = 0
    intento = 0
    while intento <= MAX_REINTENTOS:
        try:
            r = requests.get(API.format(id=food_id), headers=HEADERS,
                             params={"pn": pn, "sort": "-like"}, timeout=20)
        except requests.exceptions.RequestException as e:
            ultimo_error = f"red: {e}"
            if cortes_de_red >= len(ESPERAS_SIN_RED) or evento_detener.is_set():
                break
            # esperar de a 1 segundo, para que Ctrl+C no tenga que esperar el total
            for _ in range(ESPERAS_SIN_RED[cortes_de_red]):
                if evento_detener.is_set():
                    break
                time.sleep(1)
            cortes_de_red += 1
            continue  # un corte de red no gasta los reintentos normales
        intento += 1

        if r.status_code == 200:
            with lock_bloqueos:
                bloqueos_consecutivos = 0
            try:
                data = r.json()
            except ValueError:
                raise RuntimeError("respuesta 200 que no es JSON")
            items = (data.get("data") or {}).get("items")
            if items is None:
                raise RuntimeError("la respuesta no trae data.items")
            return items, data.get("total", 0)

        if r.status_code in (403, 429):
            with lock_bloqueos:
                bloqueos_consecutivos += 1
                if bloqueos_consecutivos >= BLOQUEOS_PARA_FRENAR:
                    evento_detener.set()
            raise BloqueoDetectado(f"HTTP {r.status_code}")

        ultimo_error = f"HTTP {r.status_code}"
        if r.status_code in (404, 400):
            break  # reintentar no ayuda
        time.sleep(2 * (intento + 1))
    raise RuntimeError(ultimo_error)


def bajar_receta(fila_id, url, total_db, tope_paginas=0, retomar_db=None, db_path=DB_PATH):
    """Baja las paginas 2..N de una receta, guardando cada GUARDAR_CADA_PAGINAS paginas.
    Devuelve un dict con cuantos comentarios nuevos guardo y si quedo completa."""
    food_id = id_food_desde_url(url)
    if food_id is None:
        return {"fila_id": fila_id, "url": url, "completa": False, "motivo": "la URL no termina en un id", "nuevos": 0}

    comentarios, motivo, nuevos = [], None, 0
    total = total_db
    pn = 2
    if retomar_db:
        # recetas parciales: seguimos desde la pagina siguiente a la ultima que ya tenemos guardada
        con = sqlite3.connect(retomar_db)
        ya = con.execute("SELECT COUNT(*) FROM comentarios WHERE recipe_id = ?", (food_id,)).fetchone()[0]
        con.close()
        pn = max(2, ya // REVIEWS_POR_PAGINA + 1)
    pn_inicial = pn
    parcial = False
    try:
        while True:
            if evento_detener.is_set():
                raise RuntimeError("detenido por bloqueos")
            ultima = math.ceil(total / REVIEWS_POR_PAGINA)
            if tope_paginas and ultima > pn_inicial - 1 + tope_paginas:
                ultima, parcial = pn_inicial - 1 + tope_paginas, True
            if pn > ultima:
                break
            time.sleep(random.uniform(PAUSA_MIN, PAUSA_MAX))
            items, total_api = pedir_pagina(food_id, pn)
            if total_api:
                total = total_api  # el total que dice la API manda
            if not items:
                raise RuntimeError(f"la pagina {pn} vino vacia (se esperaban mas comentarios)")
            comentarios.extend(items)
            if barra is not None:
                barra.update(1)
            if (pn - pn_inicial + 1) % GUARDAR_CADA_PAGINAS == 0:
                nuevos += guardar_comentarios(db_path, food_id, comentarios)
                comentarios = []
            pn += 1
    except (BloqueoDetectado, RuntimeError) as e:
        motivo = str(e)
    finally:
        # lo que quedo sin guardar (tambien si se corto con Ctrl+C o por un error)
        nuevos += guardar_comentarios(db_path, food_id, comentarios)

    return {"fila_id": fila_id, "url": url, "food_id": food_id, "completa": motivo is None,
            "motivo": motivo, "nuevos": nuevos, "total": total,
            "parcial": parcial and motivo is None}


def guardar(conn, res):
    """Marca el estado de la receta (los comentarios ya los fue guardando bajar_receta).
    Todo bajo el mismo candado que usan los hilos, para que no se bloqueen entre si."""
    with lock_base:
        cur = conn.cursor()
        if res["completa"]:
            marca = 2 if res.get("parcial") else 0
            cur.execute("UPDATE recetas SET faltan_comentarios = ? WHERE id = ?", (marca, res["fila_id"]))
        else:
            cur.execute("INSERT INTO errores (url, motivo, fecha) VALUES (?, ?, datetime('now'))",
                        (res["url"], "script3 v2: " + str(res["motivo"])))
        conn.commit()
    return res.get("nuevos", 0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DB_PATH)
    ap.add_argument("--reset-marcas", action="store_true",
                    help="vuelve a marcar como pendientes las recetas con mas de 5 reviews")
    ap.add_argument("--limite", type=int, default=None, help="maximo de recetas a procesar en esta corrida")
    ap.add_argument("--min-reviews", type=int, default=6, help="solo recetas con al menos tantas reviews (default 6)")
    ap.add_argument("--max-reviews", type=int, default=None,
                    help="solo recetas con como mucho tantas reviews (para apuntar a recetas de popularidad media)")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--parciales", action="store_true",
                    help="retoma las recetas marcadas como parciales (faltan_comentarios = 2)")
    ap.add_argument("--tope-paginas", type=int, default=0,
                    help="maximo de paginas extra por receta (5 reviews cada una). 0 = sin tope")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)

    if args.reset_marcas:
        n = conn.execute("UPDATE recetas SET faltan_comentarios = 1 WHERE total_comentarios > 5").rowcount
        conn.commit()
        print(f"Listo: {n} recetas marcadas como pendientes. Ahora corre el script sin --reset-marcas.")
        return

    sql = """SELECT id, url, total_comentarios FROM recetas
             WHERE faltan_comentarios = {marca} AND total_comentarios >= ?
             ORDER BY total_comentarios DESC"""
    sql = sql.format(marca=2 if args.parciales else 1)
    params = [args.min_reviews]
    if args.max_reviews:
        sql = sql.replace("ORDER BY", "AND total_comentarios <= ?\n             ORDER BY")
        params.append(args.max_reviews)
    if args.limite:
        sql += " LIMIT ?"
        params.append(args.limite)
    pendientes = conn.execute(sql, params).fetchall()

    # Cuantos comentarios ya tenemos de cada receta (para las parciales, que se retoman)
    ya_bajados = {}
    if args.parciales and pendientes:
        ids = [id_food_desde_url(u) for _, u, _ in pendientes]
        ids = [i for i in ids if i is not None]
        for i in range(0, len(ids), 500):
            lote = ids[i:i + 500]
            ph = ",".join("?" * len(lote))
            for rid, n in conn.execute(f"SELECT recipe_id, COUNT(*) FROM comentarios "
                                       f"WHERE recipe_id IN ({ph}) GROUP BY recipe_id", lote):
                ya_bajados[rid] = n

    def paginas_de(url, t):
        ultima = math.ceil(t / REVIEWS_POR_PAGINA)
        desde = max(2, ya_bajados.get(id_food_desde_url(url), 0) // REVIEWS_POR_PAGINA + 1)
        p = max(0, ultima - desde + 1)
        return min(p, args.tope_paginas) if args.tope_paginas else p
    paginas = sum(paginas_de(u, t) for _, u, t in pendientes)
    print(f"Recetas a completar: {len(pendientes)} | pedidos estimados: {paginas} "
          f"| tiempo aprox: {paginas * 3.5 / args.workers / 3600:.1f} h (unos 3.5 s por pedido por worker)")
    print(f"Los comentarios se guardan cada {GUARDAR_CADA_PAGINAS} paginas: si cortas con Ctrl+C, se pierde muy poco.")
    if not pendientes:
        print("No hay recetas pendientes (probablemente falta correr con --reset-marcas una vez).")
        return

    global barra
    barra = tqdm(total=paginas, unit="pedido", desc="pedidos")
    completas = incompletas = nuevos_total = 0
    cortado_por_usuario = False
    try:
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futuros = [ex.submit(bajar_receta, *f, args.tope_paginas, args.db if args.parciales else None, args.db)
                       for f in pendientes]
            for fut in as_completed(futuros):
                res = fut.result()
                nuevos_total += guardar(conn, res)
                if res["completa"]:
                    completas += 1
                else:
                    incompletas += 1
                if evento_detener.is_set():
                    for f in futuros:
                        f.cancel()
                    break
    except KeyboardInterrupt:
        cortado_por_usuario = True
        evento_detener.set()
        print("\nCortado con Ctrl+C. Lo ya guardado queda; podes volver a correr.")

    barra.close()
    print(f"\nRecetas completas: {completas} | incompletas (siguen pendientes): {incompletas}")
    print(f"Comentarios nuevos guardados (recetas terminadas en esta corrida): {nuevos_total}")
    if evento_detener.is_set() and not cortado_por_usuario:
        print("Se frenó por bloqueos del servidor (403/429). Espera unas horas antes de reintentar.")
    if completas and nuevos_total == 0:
        print("ATENCION: se marcaron recetas como completas pero no se guardo ningun comentario nuevo. Revisa.")
    conn.close()


if __name__ == "__main__":
    main()
