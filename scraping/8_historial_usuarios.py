"""
Script 22 - Baja el historial COMPLETO de reseñas de los usuarios mas utiles.

Idea (la misma que uso un compañero con vinos): la densidad de la matriz no sale
de filtrar, sale de tener historiales completos de usuarios activos. Recorriendo
receta por receta vemos solo pedazos de cada usuario; aca vamos al reves: elegimos
usuarios y bajamos todo lo que reseñaron.

Endpoint (encontrado con el script 21):
    https://api.food.com/external/v1/members/<id>/feed/reviews?pn=N
    -> 5 reseñas por pagina, y en cada respuesta el 'total' del usuario.

A QUIEN BAJAR (en este orden):
  1. Usuarios con al menos --min-en-base reseñas en tu base (ya sabemos que son activos).
  2. Ordenados por cuantas recetas "del nucleo" reseñaron: recetas con al menos
     --min-nucleo reseñas en la base. Son los que mas se cruzan con el resto, y
     completarlos es lo que mas densifica la matriz.
  3. Los "gigantes" (mas de --max-total reseñas en el sitio) se dejan para el final:
     uno solo puede llevar horas. Para bajarlos: --incluir-gigantes.

Las reseñas se guardan en la tabla 'comentarios' (las repetidas se ignoran, porque
el id de la reseña es el mismo). El avance de cada usuario queda en la tabla
'historial_usuarios', asi que se puede cortar con Ctrl+C y retomar cuando quieras.

Uso:
  python 8_historial_usuarios.py --limite 50          (prueba: 50 usuarios)
  python 8_historial_usuarios.py --limite 2000
  python 8_historial_usuarios.py --solo-ver           (muestra a quienes bajaria, sin bajar nada)
  python 8_historial_usuarios.py --incluir-gigantes   (al final: los de mas de 1500 reseñas)
"""
import argparse
import random
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from tqdm import tqdm

DB_PATH = "food_scraping.db"
API = "https://api.food.com/external/v1/members/{id}/feed/reviews"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
RESENAS_POR_PAGINA = 5
PAUSA_MIN, PAUSA_MAX = 1.0, 2.5      # pausa entre pedidos (para no saturar food.com)
GUARDAR_CADA_PAGINAS = 10
MAX_REINTENTOS = 2
BLOQUEOS_PARA_FRENAR = 5
ESPERAS_SIN_RED = [15, 30, 60, 120, 240, 300, 300]   # si se corta internet, esperar y reintentar

bloqueos_consecutivos = 0
lock_bloqueos = threading.Lock()
lock_base = threading.Lock()
evento_detener = threading.Event()
barra = None


class BloqueoDetectado(Exception):
    pass


# ---------------------------------------------------------------------------
# Pedidos
# ---------------------------------------------------------------------------

def pedir_pagina(member_id, pn):
    """Devuelve (items, total). Lanza excepcion si no pudo."""
    global bloqueos_consecutivos
    ultimo_error = "sin respuesta"
    cortes_de_red = 0
    intento = 0
    while intento <= MAX_REINTENTOS:
        try:
            r = requests.get(API.format(id=member_id), headers=HEADERS, params={"pn": pn}, timeout=20)
        except requests.exceptions.RequestException as e:
            ultimo_error = f"red: {e}"
            if cortes_de_red >= len(ESPERAS_SIN_RED) or evento_detener.is_set():
                break
            for _ in range(ESPERAS_SIN_RED[cortes_de_red]):
                if evento_detener.is_set():
                    break
                time.sleep(1)
            cortes_de_red += 1
            continue
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
            return items, data.get("total") or 0

        if r.status_code in (403, 429):
            with lock_bloqueos:
                bloqueos_consecutivos += 1
                if bloqueos_consecutivos >= BLOQUEOS_PARA_FRENAR:
                    evento_detener.set()
            raise BloqueoDetectado(f"HTTP {r.status_code}")

        ultimo_error = f"HTTP {r.status_code}"
        if r.status_code in (400, 404):
            break
        time.sleep(2 * (intento + 1))
    raise RuntimeError(ultimo_error)


# ---------------------------------------------------------------------------
# Base de datos
# ---------------------------------------------------------------------------

def preparar_tablas(con):
    con.execute("""
        CREATE TABLE IF NOT EXISTS historial_usuarios (
            member_id INTEGER PRIMARY KEY,
            total_sitio INTEGER,        -- reseñas que tiene en food.com
            paginas_bajadas INTEGER,    -- ultima pagina guardada
            estado TEXT,                -- 'en curso', 'completo', 'gigante', 'error'
            motivo TEXT,
            fecha TEXT
        )
    """)
    con.commit()


def guardar_resenas(db_path, items):
    """Inserta reseñas en 'comentarios' (las ya existentes se ignoran). Devuelve cuantas eran nuevas."""
    if not items:
        return 0
    with lock_base:
        con = sqlite3.connect(db_path, timeout=60)
        cur = con.cursor()
        nuevas = 0
        for c in items:
            cur.execute("""
                INSERT OR IGNORE INTO comentarios
                (id, recipe_id, member_id, member_name, rating, text, submitted, likes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (c.get("id"), c.get("recipeId"), c.get("memberId"), c.get("memberName"),
                  c.get("rating"), c.get("text"), c.get("submitted"),
                  (c.get("counts") or {}).get("like")))
            nuevas += cur.rowcount
        con.commit()
        con.close()
    return nuevas


def actualizar_estado(db_path, member_id, total, paginas, estado, motivo=None):
    with lock_base:
        con = sqlite3.connect(db_path, timeout=60)
        con.execute("""
            INSERT INTO historial_usuarios (member_id, total_sitio, paginas_bajadas, estado, motivo, fecha)
            VALUES (?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(member_id) DO UPDATE SET total_sitio = excluded.total_sitio,
                paginas_bajadas = excluded.paginas_bajadas, estado = excluded.estado,
                motivo = excluded.motivo, fecha = excluded.fecha
        """, (member_id, total, paginas, estado, motivo))
        con.commit()
        con.close()


def elegir_usuarios(con, min_en_base, min_nucleo, incluir_gigantes):
    """Lista de (member_id, recetas_del_nucleo, ya_en_base, paginas_ya_bajadas), en orden de prioridad."""
    print("Eligiendo usuarios (puede tardar un par de minutos con una base grande)...")
    con.execute("DROP TABLE IF EXISTS temp.nucleo")
    con.execute(f"""
        CREATE TEMP TABLE nucleo AS
        SELECT recipe_id FROM comentarios
        WHERE recipe_id IS NOT NULL AND member_id IS NOT NULL
        GROUP BY recipe_id HAVING COUNT(*) >= {int(min_nucleo)}
    """)
    con.execute("CREATE INDEX temp.idx_nucleo ON nucleo(recipe_id)")
    filas = con.execute(f"""
        SELECT c.member_id,
               COUNT(DISTINCT CASE WHEN n.recipe_id IS NOT NULL THEN c.recipe_id END) AS del_nucleo,
               COUNT(*) AS en_base
        FROM comentarios c
        LEFT JOIN nucleo n ON n.recipe_id = c.recipe_id
        WHERE c.member_id IS NOT NULL
        GROUP BY c.member_id
        HAVING COUNT(*) >= {int(min_en_base)}
        ORDER BY del_nucleo DESC, en_base DESC
    """).fetchall()

    estados = {m: (e, p) for m, e, p in con.execute(
        "SELECT member_id, estado, paginas_bajadas FROM historial_usuarios")}
    elegidos = []
    for member_id, del_nucleo, en_base in filas:
        estado, paginas = estados.get(member_id, (None, 0))
        if estado == "completo":
            continue
        if estado == "gigante" and not incluir_gigantes:
            continue
        elegidos.append((member_id, del_nucleo, en_base, paginas or 0))
    return elegidos


# ---------------------------------------------------------------------------
# Bajar un usuario
# ---------------------------------------------------------------------------

def bajar_usuario(member_id, paginas_ya, db_path, max_total, incluir_gigantes):
    """Baja las paginas que faltan del historial de un usuario, guardando cada pocas paginas."""
    nuevas, pendientes, total, pn = 0, [], None, paginas_ya + 1
    estado, motivo = "en curso", None
    try:
        while True:
            if evento_detener.is_set():
                raise RuntimeError("detenido")
            time.sleep(random.uniform(PAUSA_MIN, PAUSA_MAX))
            items, total_api = pedir_pagina(member_id, pn)
            if total_api:
                total = total_api
            if total and total > max_total and not incluir_gigantes and pn == paginas_ya + 1:
                estado, motivo = "gigante", f"{total} reseñas en el sitio"
                break
            if barra is not None:
                barra.update(1)
            if not items:
                estado = "completo"
                break
            pendientes.extend(items)
            if (pn - paginas_ya) % GUARDAR_CADA_PAGINAS == 0:
                nuevas += guardar_resenas(db_path, pendientes)
                pendientes = []
                actualizar_estado(db_path, member_id, total, pn, "en curso")
            if total and pn * RESENAS_POR_PAGINA >= total:
                estado = "completo"
                break
            pn += 1
    except (BloqueoDetectado, RuntimeError) as e:
        motivo = str(e)
        estado = "en curso" if "detenido" in motivo else "error"
        pn -= 1  # la pagina pn no se llego a guardar
    finally:
        nuevas += guardar_resenas(db_path, pendientes)
        paginas_guardadas = pn if estado == "completo" else max(paginas_ya, pn)
        if estado == "gigante":
            paginas_guardadas = paginas_ya
        actualizar_estado(db_path, member_id, total, paginas_guardadas, estado, motivo)
    return {"member_id": member_id, "estado": estado, "nuevas": nuevas, "total": total}


# ---------------------------------------------------------------------------
# Principal
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DB_PATH)
    ap.add_argument("--limite", type=int, default=None, help="maximo de usuarios en esta corrida")
    ap.add_argument("--min-en-base", type=int, default=5,
                    help="solo usuarios con al menos tantas reseñas ya guardadas (default 5)")
    ap.add_argument("--min-nucleo", type=int, default=10,
                    help="una receta es 'del nucleo' si tiene al menos tantas reseñas en la base (default 10)")
    ap.add_argument("--max-total", type=int, default=1500,
                    help="usuarios con mas reseñas que esto en el sitio se dejan para el final (default 1500)")
    ap.add_argument("--incluir-gigantes", action="store_true", help="bajar tambien a los gigantes")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--solo-ver", action="store_true", help="mostrar a quienes bajaria, sin bajar nada")
    args = ap.parse_args()

    con = sqlite3.connect(args.db, timeout=60)
    preparar_tablas(con)
    usuarios = elegir_usuarios(con, args.min_en_base, args.min_nucleo, args.incluir_gigantes)
    if args.limite:
        usuarios = usuarios[:args.limite]
    con.close()

    print(f"Usuarios a bajar en esta corrida: {len(usuarios)}")
    for member_id, del_nucleo, en_base, paginas in usuarios[:10]:
        retoma = f", retoma desde la pagina {paginas + 1}" if paginas else ""
        print(f"  usuario {member_id}: {del_nucleo} recetas del nucleo, {en_base} reseñas en tu base{retoma}")
    if len(usuarios) > 10:
        print("  ...")
    if args.solo_ver or not usuarios:
        return
    print(f"Cada pedido trae {RESENAS_POR_PAGINA} reseñas y tarda unos 3.5 s por worker "
          f"(~{3600 * args.workers / 3.5 * RESENAS_POR_PAGINA:,.0f} reseñas por hora con {args.workers} workers).")
    print(f"Se guarda cada {GUARDAR_CADA_PAGINAS} paginas: si cortas con Ctrl+C, se pierde muy poco.\n")

    global barra
    barra = tqdm(unit="pedido", desc="pedidos")
    completos = gigantes = errores = nuevas_total = 0
    cortado_por_usuario = False
    try:
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futuros = [ex.submit(bajar_usuario, m, p, args.db, args.max_total, args.incluir_gigantes)
                       for m, _, _, p in usuarios]
            hechos = 0
            for fut in as_completed(futuros):
                res = fut.result()
                hechos += 1
                nuevas_total += res["nuevas"]
                completos += res["estado"] == "completo"
                gigantes += res["estado"] == "gigante"
                errores += res["estado"] == "error"
                barra.set_postfix(usuarios=f"{hechos}/{len(usuarios)}", nuevas=nuevas_total)
                if evento_detener.is_set():
                    for f in futuros:
                        f.cancel()
                    break
    except KeyboardInterrupt:
        cortado_por_usuario = True
        evento_detener.set()
        print("\nCortado con Ctrl+C. Lo ya guardado queda; al volver a correr, cada usuario sigue donde quedo.")
    barra.close()

    print(f"\nUsuarios completos: {completos} | gigantes dejados para el final: {gigantes} | con error: {errores}")
    print(f"Reseñas nuevas guardadas (usuarios terminados en esta corrida): {nuevas_total}")
    if evento_detener.is_set() and not cortado_por_usuario:
        print("Se freno por bloqueos del servidor (403/429). Espera unas horas antes de reintentar.")


if __name__ == "__main__":
    main()
