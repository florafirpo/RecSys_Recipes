"""
Recomendador de recetas, adaptado del esquema del profesor
(libros -> recetas, interacciones, vistos) a tu base recetas_app.db.

Tres estrategias, de menor a mayor personalizacion:
  - recomendador_azar: baseline, recetas al azar entre las que el
    usuario no vio ni valoro todavia.
  - recomendador_top_n: popularidad -- recetas con mas puntos (suma de
    ratings) en la tabla 'interacciones' de la base que se esta usando.
  - recomendador_perfil: basado en contenido -- arma un perfil del
    usuario segun que categorias y que autores le gustaron (valoro
    bien) en el pasado, y recomienda recetas de esas categorias/autores
    que todavia no probo.

recomendar() decide cual usar segun cuanto historial tiene el usuario
(mismo patron del profesor: cold start -> top_n; con historial -> perfil,
completando con top_n si hacen falta mas recomendaciones).

Por defecto trabaja sobre recetas_app.db (config.DB_APP). Para apuntar a
otra base (por ejemplo recetas_train.db al evaluar) se puede definir la
variable de entorno RECETAS_DB, o cambiar recomendador.DATABASE_FILE
desde codigo.
"""

import sqlite3
import os

import config

DATABASE_FILE = os.environ.get("RECETAS_DB", config.DB_APP)

# Hiperparametros (se cambian en config.py):
#  - RATING_POSITIVO: a partir de que rating (1 a 5 estrellas) consideramos
#    que a un usuario "le gusto" una receta.
#  - MAX_VALORADAS_COLD_START: con esta cantidad de recetas valoradas o
#    menos, el usuario es cold start y se le recomienda por popularidad.
RATING_POSITIVO = config.RATING_POSITIVO
MAX_VALORADAS_COLD_START = config.MAX_VALORADAS_COLD_START


def sql_select(query, params=None):
    con = sqlite3.connect(DATABASE_FILE)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    res = cur.execute(query, params) if params else cur.execute(query)
    ret = res.fetchall()
    con.close()
    return ret


def sql_execute(query, params=None):
    con = sqlite3.connect(DATABASE_FILE)
    cur = con.cursor()
    res = cur.execute(query, params) if params else cur.execute(query)
    con.commit()
    con.close()
    return res


###

def items_valorados(id_lector):
    query = "SELECT id_receta FROM interacciones WHERE id_lector = ?"
    rows = sql_select(query, [id_lector])
    return [r["id_receta"] for r in rows]


def items_vistos(id_lector):
    query = "SELECT id_receta FROM vistos WHERE id_lector = ?"
    rows = sql_select(query, [id_lector])
    return [r["id_receta"] for r in rows]


def items_desconocidos(id_lector):
    query = """
        SELECT id
          FROM recetas
         WHERE id NOT IN (SELECT id_receta FROM interacciones WHERE id_lector = ?)
           AND id NOT IN (SELECT id_receta FROM vistos WHERE id_lector = ?)
    """
    rows = sql_select(query, [id_lector, id_lector])
    return [r["id"] for r in rows]


def insertar_vistos(id_lector, id_recetas):
    for id_receta in id_recetas:
        query = "INSERT INTO vistos (id_lector, id_receta, fecha) VALUES (?, ?, date('now')) ON CONFLICT DO NOTHING;"
        sql_execute(query, [id_lector, id_receta])


def insertar_interaccion(id_lector, id_receta, rating):
    query = """
        INSERT INTO interacciones (id_lector, id_receta, rating, fecha) VALUES (?, ?, ?, date('now'))
        ON CONFLICT(id_lector, id_receta) DO UPDATE SET rating = excluded.rating, fecha = excluded.fecha;
    """
    sql_execute(query, [id_lector, id_receta, rating])


###

def reset_usuario(id_lector):
    sql_execute("DELETE FROM vistos WHERE id_lector = ?", [id_lector])
    sql_execute("DELETE FROM interacciones WHERE id_lector = ?", [id_lector])
    asegurar_tabla_lote()
    sql_execute("DELETE FROM lote_actual WHERE id_lector = ?", [id_lector])


###

# El "lote actual" es la tanda de recomendaciones que el usuario esta
# mirando ahora. Se guarda para que la pagina no cambie cada vez que se
# recarga o se vuelve a entrar: solo cambia cuando el usuario pide
# "ver otras 10".

def asegurar_tabla_lote():
    sql_execute("""
        CREATE TABLE IF NOT EXISTS lote_actual (
            id_lector INTEGER,
            posicion INTEGER,
            id_receta INTEGER,
            PRIMARY KEY (id_lector, posicion)
        )
    """)


def recomendar_lote(id_lector, N=10, nuevo=False):
    """Devuelve (recetas, algoritmo). Si el usuario ya tiene un lote
    guardado lo repite tal cual; si no tiene, o si nuevo=True, genera
    uno nuevo con recomendar() y lo guarda."""
    asegurar_tabla_lote()

    if not nuevo:
        guardadas = sql_select("""
            SELECT recetas.*
              FROM lote_actual
              JOIN recetas ON recetas.id = lote_actual.id_receta
             WHERE lote_actual.id_lector = ?
             ORDER BY lote_actual.posicion
        """, [id_lector])
        if guardadas:
            return guardadas, "lote_guardado"

    rec, algoritmo = recomendar(id_lector, N)

    sql_execute("DELETE FROM lote_actual WHERE id_lector = ?", [id_lector])
    for posicion, r in enumerate(rec):
        sql_execute(
            "INSERT INTO lote_actual (id_lector, posicion, id_receta) VALUES (?, ?, ?)",
            [id_lector, posicion, r["id"]]
        )
    return rec, algoritmo


###

def buscar_usuario_por_nombre(username):
    """Busca un usuario por nombre (sin importar mayusculas/minusculas).
    Devuelve su member_id, o None si no existe todavia."""
    query = "SELECT member_id FROM usuarios WHERE LOWER(username) = LOWER(?)"
    rows = sql_select(query, [username])
    return rows[0]["member_id"] if rows else None


def crear_usuario(username):
    """Da de alta un usuario nuevo (alguien que todavia no estaba en la
    base) y devuelve el member_id que le asignamos. Como los member_id
    originales son ids reales de food.com, a los usuarios nuevos les
    asignamos ids que arrancan en 900000 para no pisar ninguno existente."""
    fila = sql_select("SELECT MAX(member_id) AS maximo FROM usuarios")[0]
    maximo_actual = fila["maximo"] or 0
    nuevo_id = max(maximo_actual + 1, 900000)

    query = """
        INSERT INTO usuarios (member_id, username, nombre, bio, ubicacion, rating_promedio)
        VALUES (?, ?, ?, NULL, NULL, NULL)
    """
    sql_execute(query, [nuevo_id, username, username])
    return nuevo_id


def obtener_username(id_lector):
    """Nombre de usuario a mostrar en la pagina. Si por algun motivo no
    esta en 'usuarios' (no deberia pasar), mostramos el id como texto."""
    rows = sql_select("SELECT username FROM usuarios WHERE member_id = ?", [id_lector])
    return rows[0]["username"] if rows else str(id_lector)


###

def obtener_receta(id_receta):
    """Una receta puntual, para la pagina de detalle."""
    rows = sql_select("SELECT * FROM recetas WHERE id = ?", [id_receta])
    return rows[0] if rows else None


def obtener_ingredientes(id_receta):
    """Lista de ingredientes de una receta, en el orden original."""
    rows = sql_select("""
        SELECT texto_completo
          FROM ingredientes
         WHERE recipe_id = ?
         ORDER BY orden
    """, [id_receta])
    return [r["texto_completo"] for r in rows]


###

def recomendador_azar(id_lector):
    rec = sql_select("""
        SELECT *
          FROM recetas
         WHERE title IS NOT NULL
           AND id NOT IN (SELECT id_receta FROM interacciones WHERE id_lector = ?)
           AND id NOT IN (SELECT id_receta FROM vistos WHERE id_lector = ?)
         ORDER BY RANDOM()
    """, [id_lector, id_lector])
    return rec


def recomendador_top_n(id_lector):
    # Popularidad calculada con las interacciones de ESTA base:
    # suma de ratings (= cantidad de reseñas x rating promedio).
    # Antes usaba rating_value/rating_count de food.com, pero esos numeros
    # incluyen las reseñas que escondemos en test: era leakage y la
    # evaluacion de top_n quedaba inflada.
    rec = sql_select("""
        SELECT recetas.*
          FROM recetas
          JOIN (SELECT id_receta, SUM(rating) AS puntos, COUNT(*) AS cant
                  FROM interacciones
                 GROUP BY id_receta) AS popularidad ON popularidad.id_receta = recetas.id
         WHERE title IS NOT NULL
           AND id NOT IN (SELECT id_receta FROM interacciones WHERE id_lector = ?)
           AND id NOT IN (SELECT id_receta FROM vistos WHERE id_lector = ?)
         ORDER BY popularidad.puntos DESC, popularidad.cant DESC
    """, [id_lector, id_lector])
    return rec


def recomendador_perfil(id_lector):
    # LEFT JOIN: una receta suma puntos por su categoria Y/O por su autor.
    # (Con JOIN comun tenia que coincidir en las dos cosas, y como el 60% de
    # los autores firma una sola receta, casi todo quedaba afuera.)
    # COALESCE(x, 0) pone 0 cuando la receta no coincide en ese criterio.
    rec = sql_select(f"""
        SELECT *, COALESCE(perfil_categoria.cant, 0)*0.8
                + COALESCE(perfil_autor.cant, 0)*0.2 AS score -- 0.8 y 0.2 son hiperparametros
          FROM recetas
          LEFT JOIN (SELECT category, count(*) AS cant
                  FROM recetas JOIN interacciones ON recetas.id = interacciones.id_receta
                 WHERE id_lector = ?
                   AND rating >= {RATING_POSITIVO}
                 GROUP BY 1) AS perfil_categoria USING (category)
          LEFT JOIN (SELECT author_id, count(*) AS cant
                  FROM recetas JOIN interacciones ON recetas.id = interacciones.id_receta
                 WHERE id_lector = ?
                   AND rating >= {RATING_POSITIVO}
                 GROUP BY 1) AS perfil_autor USING (author_id)
         WHERE (perfil_categoria.cant IS NOT NULL OR perfil_autor.cant IS NOT NULL)
           AND title IS NOT NULL
           AND id NOT IN (SELECT id_receta FROM interacciones WHERE id_lector = ?)
           AND id NOT IN (SELECT id_receta FROM vistos WHERE id_lector = ?)
         ORDER BY score DESC
    """, [id_lector, id_lector, id_lector, id_lector])
    return rec


def top_populares(N=10):
    """Las N recetas mas populares en general (sin importar el usuario),
    para la seccion fija de 'Las más populares' de la pagina. Usa la
    misma popularidad que recomendador_top_n."""
    rec = sql_select("""
        SELECT recetas.*
          FROM recetas
          JOIN (SELECT id_receta, SUM(rating) AS puntos, COUNT(*) AS cant
                  FROM interacciones
                 GROUP BY id_receta) AS popularidad ON popularidad.id_receta = recetas.id
         WHERE title IS NOT NULL
         ORDER BY popularidad.puntos DESC, popularidad.cant DESC
         LIMIT ?
    """, [N])
    return rec


def recomendar(id_lector, N=10, registrar_vistos=True):
    """Devuelve N recetas recomendadas para el usuario id_lector.
    Con registrar_vistos=False no marca las recetas como vistas
    (lo usa la evaluacion, para no modificar la base de entrenamiento)."""
    cant_items_valorados = len(items_valorados(id_lector))

    if cant_items_valorados <= MAX_VALORADAS_COLD_START:  # cold start
        rec = recomendador_top_n(id_lector)
        algoritmo = "top_n"
    else:
        rec = recomendador_perfil(id_lector)
        algoritmo = "perfil"

        if len(rec) < N:
            # Evitamos repetir recetas que perfil ya habia recomendado
            ids_perfil = {r["id"] for r in rec}
            rec = rec + [r for r in recomendador_top_n(id_lector) if r["id"] not in ids_perfil]
            algoritmo = "perfil+top_n"

    rec = rec[:N]
    if registrar_vistos:
        insertar_vistos(id_lector, [r["id"] for r in rec])

    return rec, algoritmo
