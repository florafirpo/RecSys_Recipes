"""
Script 7 - Fase 4: Scraper de perfiles de usuario.

Confirmado con un HTML real (perfil_test.html) que la estructura es:

  <section class="fd-page-profile" data-id="58104" data-username="Rita1652">
    ...
    <h3>Rita L</h3>
    <div class="profileusername">@Rita1652</div>
    <div class="bio">...</div>
    <a class="user-followers">...<span class="count">552</span></a>
    <a class="user-following">...<span class="count">20</span></a>
    <span class="rating-text">4.7 avg</span>
    <div><i class="icon-fdc-map-pin"></i> Jamesburg, New Jersey</div>
    <div><i class="icon-fdc-profile"></i> Joined 10/2002</div>
    <div class="rib-text">Contributor</div>  (puede no existir)

Un GET normal con 'requests' (sin navegador, sin JS) devuelve esta
página completa sin redirecciones -- ya lo confirmamos con un test.

Estrategia:
  - Prioriza a los usuarios con MÁS actividad primero (comentarios +
    recetas subidas), igual que hicimos con las recetas.
  - Resumible: usa la tabla 'usuarios' con scraped_ok para no repetir
    trabajo entre corridas.
  - Ritmo conservador (pausa random 1.2-3s, pocos hilos en simultáneo)
    y un freno automático si el sitio empieza a devolver 403/429
    seguidos (mismo mecanismo que usamos para las recetas).
  - LIMITE_DIARIO para ir corriendo de a tandas, como el resto.
"""

import requests
import sqlite3
import time
import random
import threading
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from bs4 import BeautifulSoup
from tqdm import tqdm

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
DB_PATH = "food_scraping.db"

MAX_WORKERS = 3
PAUSA_MIN = 1.2
PAUSA_MAX = 3.0
MAX_REINTENTOS = 2
LIMITE_DIARIO = 20000  # <-- ajustá esto: cuántos usuarios procesar por corrida

BLOQUEOS_PARA_FRENAR = 5
bloqueos_consecutivos = 0
lock_bloqueos = threading.Lock()
evento_detener = threading.Event()


class BloqueoDetectado(Exception):
    def __init__(self, status_code):
        self.status_code = status_code
        super().__init__(f"Bloqueado por el servidor (HTTP {status_code})")


def crear_tabla_usuarios(conn):
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            member_id INTEGER PRIMARY KEY,
            username TEXT,
            nombre TEXT,
            bio TEXT,
            ubicacion TEXT,
            fecha_registro TEXT,
            seguidores INTEGER,
            siguiendo INTEGER,
            rating_promedio REAL,
            estado TEXT,
            total_actividad INTEGER,
            scraped_ok INTEGER DEFAULT 0
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS errores_usuarios (
            member_id INTEGER,
            motivo TEXT,
            fecha TEXT
        )
    """)
    conn.commit()


def cargar_usuarios_priorizados(conn):
    """La primera vez, calcula todos los usuarios únicos (autores + comentaristas),
    su nivel de actividad, y los carga en la tabla 'usuarios' ordenables por prioridad."""
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM usuarios")
    if cursor.fetchone()[0] > 0:
        print("La tabla 'usuarios' ya tiene datos cargados, no la vuelvo a poblar.")
        return

    print("Calculando actividad de cada usuario único (esto es todo local, no pide nada a internet)...")
    cursor.execute("""
        INSERT INTO usuarios (member_id, total_actividad, scraped_ok)
        SELECT member_id, SUM(cnt), 0
        FROM (
            SELECT member_id, COUNT(*) AS cnt
            FROM comentarios
            WHERE member_id IS NOT NULL
            GROUP BY member_id

            UNION ALL

            SELECT author_id AS member_id, COUNT(*) AS cnt
            FROM recetas
            WHERE author_id IS NOT NULL
            GROUP BY author_id
        )
        GROUP BY member_id
    """)
    conn.commit()

    cursor.execute("SELECT COUNT(*) FROM usuarios")
    print(f"Cargados {cursor.fetchone()[0]} usuarios únicos, listos para priorizar por actividad.")


def parse_int(texto):
    if not texto:
        return None
    numeros = re.sub(r"[^\d]", "", texto)
    return int(numeros) if numeros else None


def parse_float(texto):
    if not texto:
        return None
    match = re.search(r"[\d.]+", texto)
    return float(match.group()) if match else None


def extraer_datos_perfil(html):
    soup = BeautifulSoup(html, "html.parser")
    section = soup.find("section", class_="fd-page-profile")
    if section is None:
        return None  # no es una página de perfil válida (usuario borrado, etc.)

    resultado = {}

    h3 = section.find("h3")
    resultado["nombre"] = h3.get_text(strip=True) if h3 else None

    username_div = section.find("div", class_="profileusername")
    resultado["username"] = username_div.get_text(strip=True).lstrip("@") if username_div else None

    bio_div = section.find("div", class_="bio")
    resultado["bio"] = bio_div.get_text(strip=True) if bio_div else None

    followers_a = section.find("a", class_="user-followers")
    count_span = followers_a.find("span", class_="count") if followers_a else None
    resultado["seguidores"] = parse_int(count_span.get_text()) if count_span else None

    following_a = section.find("a", class_="user-following")
    count_span = following_a.find("span", class_="count") if following_a else None
    resultado["siguiendo"] = parse_int(count_span.get_text()) if count_span else None

    rating_span = section.find("span", class_="rating-text")
    resultado["rating_promedio"] = parse_float(rating_span.get_text()) if rating_span else None

    ubicacion, fecha_registro = None, None
    for i_tag in section.find_all("i"):
        clases = i_tag.get("class", []) or []
        texto_padre = i_tag.parent.get_text(" ", strip=True)
        if "icon-fdc-map-pin" in clases:
            ubicacion = texto_padre or None
        elif "icon-fdc-profile" in clases:
            fecha_registro = texto_padre.replace("Joined", "").strip() or None

    resultado["ubicacion"] = ubicacion
    resultado["fecha_registro"] = fecha_registro

    status_div = section.find("div", class_="rib-text")
    resultado["estado"] = status_div.get_text(strip=True) if status_div else None

    return resultado


def pedido_con_reintentos(url):
    global bloqueos_consecutivos

    for _ in range(MAX_REINTENTOS + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)

            if r.status_code == 200:
                with lock_bloqueos:
                    bloqueos_consecutivos = 0
                return r.text

            if r.status_code in (403, 429):
                with lock_bloqueos:
                    bloqueos_consecutivos += 1
                    if bloqueos_consecutivos >= BLOQUEOS_PARA_FRENAR:
                        evento_detener.set()
                raise BloqueoDetectado(r.status_code)

            return None

        except requests.exceptions.RequestException:
            time.sleep(1)
    return None


def procesar_usuario(member_id):
    if evento_detener.is_set():
        return {"member_id": member_id, "ok": False, "motivo": "detenido por bloqueo"}

    try:
        time.sleep(random.uniform(PAUSA_MIN, PAUSA_MAX))
        url = f"https://www.food.com/user/{member_id}"
        html = pedido_con_reintentos(url)

        if html is None:
            return {"member_id": member_id, "ok": False, "motivo": "sin respuesta HTML"}

        datos = extraer_datos_perfil(html)
        if datos is None:
            return {"member_id": member_id, "ok": False, "motivo": "no es una página de perfil válida"}

        return {"member_id": member_id, "ok": True, "datos": datos}

    except Exception as e:
        return {"member_id": member_id, "ok": False, "motivo": str(e)}


def guardar_resultado(conn, resultado):
    cursor = conn.cursor()

    if not resultado["ok"]:
        cursor.execute(
            "INSERT INTO errores_usuarios (member_id, motivo, fecha) VALUES (?, ?, datetime('now'))",
            (resultado["member_id"], resultado.get("motivo", "desconocido"))
        )
        conn.commit()
        return

    d = resultado["datos"]
    cursor.execute("""
        UPDATE usuarios
        SET username = ?, nombre = ?, bio = ?, ubicacion = ?, fecha_registro = ?,
            seguidores = ?, siguiendo = ?, rating_promedio = ?, estado = ?, scraped_ok = 1
        WHERE member_id = ?
    """, (
        d.get("username"), d.get("nombre"), d.get("bio"), d.get("ubicacion"),
        d.get("fecha_registro"), d.get("seguidores"), d.get("siguiendo"),
        d.get("rating_promedio"), d.get("estado"), resultado["member_id"],
    ))
    conn.commit()


def main():
    conn = sqlite3.connect(DB_PATH)
    crear_tabla_usuarios(conn)
    cargar_usuarios_priorizados(conn)

    cursor = conn.cursor()
    cursor.execute("""
        SELECT member_id FROM usuarios
        WHERE scraped_ok = 0
        ORDER BY total_actividad DESC
        LIMIT ?
    """, (LIMITE_DIARIO,))
    pendientes = [fila[0] for fila in cursor.fetchall()]

    print(f"Usuarios a procesar en esta corrida: {len(pendientes)}")
    if not pendientes:
        print("No quedan usuarios pendientes.")
        conn.close()
        return

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futuros = {executor.submit(procesar_usuario, mid): mid for mid in pendientes}

        for futuro in tqdm(as_completed(futuros), total=len(pendientes)):
            guardar_resultado(conn, futuro.result())

            if evento_detener.is_set():
                for f in futuros:
                    f.cancel()
                break

    conn.close()

    if evento_detener.is_set():
        print("\n⚠️  CORTADO: bloqueos consecutivos detectados. Esperá antes de reintentar.")
    else:
        print("Listo esta tanda de usuarios.")


if __name__ == "__main__":
    main()
