"""
Recomendador de recetas, adaptado del esquema del profesor
(libros -> recetas, interacciones, vistos) a tu base recetas_app.db.

Cuatro estrategias, de menor a mayor personalizacion:
  - recomendador_azar: baseline, recetas al azar entre las que el
    usuario no vio ni valoro todavia.
  - recomendador_top_n: popularidad -- recetas con mas puntos (suma de
    ratings) en la tabla 'interacciones' de la base que se esta usando.
  - recomendador_perfil: basado en contenido -- arma un perfil del
    usuario segun que categorias y que autores le gustaron (valoro
    bien) en el pasado, y recomienda recetas de esas categorias/autores
    que todavia no probo.
  - recomendador_ease: filtrado colaborativo con EASE (Steck, 2019). Es el
    que mejor rindio en la evaluacion (ver README).

recomendar() es la que usa la pagina y decide segun cuanto historial tiene
el usuario: cold start -> top_n; con historial -> EASE, completando con
top_n si hacen falta mas recomendaciones. (Antes usaba perfil, que en la
evaluacion acertaba bastante menos: hit rate 20% contra 51% de EASE.)

Por defecto trabaja sobre recetas_app.db (config.DB_APP). Para apuntar a
otra base (por ejemplo recetas_train.db al evaluar) se puede definir la
variable de entorno RECETAS_DB, o cambiar recomendador.DATABASE_FILE
desde codigo.
"""

import sqlite3
import os

import numpy as np

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


# ---------------------------------------------------------------------------
# Señales livianas: "Me tienta" y "No es para mí"
# ---------------------------------------------------------------------------
# Valorar con estrellas pide haber cocinado la receta, y la mayoria de la
# gente entra solo a mirar. Por eso hay dos señales mas livianas:
#   - 'tienta': la guarda en "Guardadas" y cuenta como interes positivo
#     (EASE la usa igual que una receta reseñada, y suma para salir del
#     cold start).
#   - 'no': no se la vuelve a recomendar.
# Se guardan en la tabla 'senales', aparte de 'interacciones', para no
# mezclarlas con las reseñas reales (que son las que usa la evaluacion).

def asegurar_tabla_senales():
    sql_execute("""
        CREATE TABLE IF NOT EXISTS senales (
            id_lector INTEGER,
            id_receta INTEGER,
            tipo TEXT,
            fecha TEXT,
            PRIMARY KEY (id_lector, id_receta)
        )
    """)


def marcar_senal(id_lector, id_receta, tipo):
    """Guarda la señal ('tienta' o 'no'). Marcar 'tienta' sobre una receta
    que ya estaba guardada la desguarda (funciona como un boton on/off)."""
    asegurar_tabla_senales()
    actual = mi_senal(id_lector, id_receta)
    if tipo == "tienta" and actual == "tienta":
        sql_execute("DELETE FROM senales WHERE id_lector = ? AND id_receta = ?", [id_lector, id_receta])
        return None
    sql_execute("""
        INSERT INTO senales (id_lector, id_receta, tipo, fecha) VALUES (?, ?, ?, date('now'))
        ON CONFLICT(id_lector, id_receta) DO UPDATE SET tipo = excluded.tipo, fecha = excluded.fecha;
    """, [id_lector, id_receta, tipo])
    return tipo


def mi_senal(id_lector, id_receta):
    """'tienta', 'no' o None."""
    asegurar_tabla_senales()
    filas = sql_select("SELECT tipo FROM senales WHERE id_lector = ? AND id_receta = ?", [id_lector, id_receta])
    return filas[0]["tipo"] if filas else None


def items_con_senal(id_lector, tipo):
    asegurar_tabla_senales()
    filas = sql_select("SELECT id_receta FROM senales WHERE id_lector = ? AND tipo = ?", [id_lector, tipo])
    return [f["id_receta"] for f in filas]


def items_positivos(id_lector):
    """Lo que sabemos que le interesa: lo que valoro + lo que le tienta.
    Es lo que usa EASE y lo que cuenta para salir del cold start."""
    return set(items_valorados(id_lector)) | set(items_con_senal(id_lector, "tienta"))


def mi_rating(id_lector, id_receta):
    filas = sql_select("SELECT rating FROM interacciones WHERE id_lector = ? AND id_receta = ?",
                       [id_lector, id_receta])
    return filas[0]["rating"] if filas else None


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
    asegurar_tabla_senales()
    sql_execute("DELETE FROM senales WHERE id_lector = ?", [id_lector])
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


def reemplazar_en_lote(id_lector, id_receta):
    """Saca UNA receta del lote actual (por ejemplo, la que el usuario acaba
    de abrir y valorar) y pone en su lugar una recomendacion nueva, en la
    misma posicion. Las otras recetas del lote quedan como estaban.
    La nueva sale de recomendar(): como las recetas del lote ya estan en
    'vistos', no se repite ninguna. Si el usuario acaba de llegar a 3
    valoradas, la nueva ya viene de EASE.
    Devuelve la receta nueva, o None si id_receta no estaba en el lote."""
    asegurar_tabla_lote()
    filas = sql_select(
        "SELECT posicion FROM lote_actual WHERE id_lector = ? AND id_receta = ?",
        [id_lector, id_receta],
    )
    if not filas:
        return None
    posicion = filas[0]["posicion"]

    nuevas, _ = recomendar(id_lector, N=1)  # la registra como vista
    if not nuevas:
        # No quedan recetas sin ver: se saca la receta del lote y listo
        sql_execute("DELETE FROM lote_actual WHERE id_lector = ? AND posicion = ?", [id_lector, posicion])
        return None
    nueva = nuevas[0]
    sql_execute(
        "UPDATE lote_actual SET id_receta = ? WHERE id_lector = ? AND posicion = ?",
        [nueva["id"], id_lector, posicion],
    )
    return nueva


def recetas_vistas(id_lector, N=60, filtro="todas"):
    """Historial para volver a ver recetas, de la mas reciente a la mas vieja.
    Cada receta trae mi_rating (sus estrellas o None) y mi_senal.
    filtro:
      - 'todas'      : todo lo que se le mostro
      - 'guardadas'  : las que marco "Me tienta" (aunque no se le hayan mostrado)
      - 'pendientes' : las que se le mostraron y todavia no valoro
      - 'valoradas'  : las que valoro con estrellas"""
    asegurar_tabla_senales()
    if filtro == "guardadas":
        return sql_select("""
            SELECT recetas.*, interacciones.rating AS mi_rating, senales.tipo AS mi_senal
              FROM senales
              JOIN recetas ON recetas.id = senales.id_receta
              LEFT JOIN interacciones ON interacciones.id_lector = senales.id_lector
                                     AND interacciones.id_receta = senales.id_receta
             WHERE senales.id_lector = ? AND senales.tipo = 'tienta'
             ORDER BY senales.rowid DESC
             LIMIT ?
        """, [id_lector, N])

    condicion = {
        "pendientes": "AND interacciones.rating IS NULL AND COALESCE(senales.tipo, '') <> 'no'",
        "valoradas": "AND interacciones.rating IS NOT NULL",
    }.get(filtro, "")
    return sql_select(f"""
        SELECT recetas.*, interacciones.rating AS mi_rating, senales.tipo AS mi_senal
          FROM vistos
          JOIN recetas ON recetas.id = vistos.id_receta
          LEFT JOIN interacciones ON interacciones.id_lector = vistos.id_lector
                                 AND interacciones.id_receta = vistos.id_receta
          LEFT JOIN senales ON senales.id_lector = vistos.id_lector
                           AND senales.id_receta = vistos.id_receta
         WHERE vistos.id_lector = ? {condicion}
         ORDER BY vistos.rowid DESC
         LIMIT ?
    """, [id_lector, N])


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


def tiene_columna(tabla, columna):
    return any(c["name"] == columna for c in sql_select(f"PRAGMA table_info({tabla})"))


def obtener_ingredientes(id_receta):
    """Lista de ingredientes en el orden original, con su cantidad adelante
    si la base la tiene ("1 1/2 cups flour")."""
    if tiene_columna("ingredientes", "cantidad"):
        rows = sql_select("""
            SELECT TRIM(COALESCE(cantidad || ' ', '') || COALESCE(texto_completo, '')) AS texto
              FROM ingredientes WHERE recipe_id = ? ORDER BY orden
        """, [id_receta])
    else:
        rows = sql_select("SELECT texto_completo AS texto FROM ingredientes WHERE recipe_id = ? ORDER BY orden",
                          [id_receta])
    return [r["texto"] for r in rows]


def obtener_preparacion(id_receta):
    """Pasos de preparacion, en orden. Lista vacia si la base no los tiene."""
    existe = sql_select("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'preparacion'")
    if not existe:
        return []
    rows = sql_select("SELECT texto FROM preparacion WHERE recipe_id = ? ORDER BY paso", [id_receta])
    return [r["texto"] for r in rows]


###

def recomendador_azar(id_lector):
    asegurar_tabla_senales()
    rec = sql_select("""
        SELECT *
          FROM recetas
         WHERE title IS NOT NULL
           AND id NOT IN (SELECT id_receta FROM interacciones WHERE id_lector = ?)
           AND id NOT IN (SELECT id_receta FROM vistos WHERE id_lector = ?)
           AND id NOT IN (SELECT id_receta FROM senales WHERE id_lector = ?)
         ORDER BY RANDOM()
    """, [id_lector, id_lector, id_lector])
    return rec


def recomendador_top_n(id_lector):
    # Popularidad calculada con las interacciones de ESTA base:
    # suma de ratings (= cantidad de reseñas x rating promedio).
    # Antes usaba rating_value/rating_count de food.com, pero esos numeros
    # incluyen las reseñas que escondemos en test: era leakage y la
    # evaluacion de top_n quedaba inflada.
    # Tampoco recomienda lo que ya tiene una señal (guardada o descartada).
    asegurar_tabla_senales()
    rec = sql_select("""
        SELECT recetas.*
          FROM recetas
          JOIN (SELECT id_receta, SUM(rating) AS puntos, COUNT(*) AS cant
                  FROM interacciones
                 GROUP BY id_receta) AS popularidad ON popularidad.id_receta = recetas.id
         WHERE title IS NOT NULL
           AND id NOT IN (SELECT id_receta FROM interacciones WHERE id_lector = ?)
           AND id NOT IN (SELECT id_receta FROM vistos WHERE id_lector = ?)
           AND id NOT IN (SELECT id_receta FROM senales WHERE id_lector = ?)
         ORDER BY popularidad.puntos DESC, popularidad.cant DESC
    """, [id_lector, id_lector, id_lector])
    return rec


def recomendador_perfil(id_lector):
    # LEFT JOIN: una receta suma puntos por su categoria Y/O por su autor.
    # (Con JOIN comun tenia que coincidir en las dos cosas, y como el 60% de
    # los autores firma una sola receta, casi todo quedaba afuera.)
    # COALESCE(x, 0) pone 0 cuando la receta no coincide en ese criterio.
    asegurar_tabla_senales()
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
           AND id NOT IN (SELECT id_receta FROM senales WHERE id_lector = ?)
         ORDER BY score DESC
    """, [id_lector, id_lector, id_lector, id_lector, id_lector])
    return rec


# ---------------------------------------------------------------------------
# EASE
# ---------------------------------------------------------------------------
# EASE aprende una matriz B de pesos receta x receta: B[i, j] dice cuanto
# "empuja" haber reseñado la receta i a reseñar la receta j. El puntaje de
# un usuario para cada receta es la suma de las filas de B de las recetas
# que reseño.
#
# Entrenar B (invertir una matriz de recetas x recetas) tarda un par de
# segundos, asi que se hace una vez y se guarda en memoria (_modelo_ease).
# Para recomendar no hace falta reentrenar: cada vez se leen de la base
# las recetas que el usuario reseño hasta ese momento, asi que una
# valoracion nueva en la pagina cambia sus recomendaciones enseguida.
# B se vuelve a entrenar solo si cambia la base o si las interacciones
# crecieron mas de un 5% desde el ultimo entrenamiento.

_modelo_ease = {}
CRECIMIENTO_PARA_REENTRENAR = 1.05


def pesos_ease(X, lambda_):
    """Matriz B de EASE para una matriz binaria X (usuarios x recetas).
    lambda_ es la regularizacion: cuanto mas alta, mas suaves los pesos."""
    G = X.T @ X + lambda_ * np.eye(X.shape[1])
    P = np.linalg.inv(G)
    B = -P / np.diag(P)
    np.fill_diagonal(B, 0)  # una receta no se recomienda a si misma
    return B


def modelo_ease():
    """Devuelve el modelo EASE entrenado con la base actual (lo entrena si hace falta)."""
    cantidad = sql_select("SELECT COUNT(*) AS n FROM interacciones")[0]["n"]
    modelo = _modelo_ease.get("modelo")
    if (modelo is None or modelo["base"] != DATABASE_FILE
            or cantidad > modelo["interacciones"] * CRECIMIENTO_PARA_REENTRENAR):
        recetas = [r["id"] for r in sql_select("SELECT id FROM recetas WHERE title IS NOT NULL ORDER BY id")]
        columna_de = {r: c for c, r in enumerate(recetas)}
        filas = sql_select("SELECT id_lector, id_receta FROM interacciones")
        usuarios = sorted({f["id_lector"] for f in filas})
        fila_de = {u: f for f, u in enumerate(usuarios)}
        X = np.zeros((len(usuarios), len(recetas)))
        for f in filas:
            if f["id_receta"] in columna_de:
                X[fila_de[f["id_lector"]], columna_de[f["id_receta"]]] = 1
        modelo = {
            "base": DATABASE_FILE,
            "interacciones": cantidad,
            "recetas": recetas,
            "columna_de": columna_de,
            # float32 ocupa la mitad de memoria y alcanza para ordenar
            "B": pesos_ease(X, config.LAMBDA_EASE).astype(np.float32),
        }
        _modelo_ease["modelo"] = modelo
    return modelo


def recomendador_ease(id_lector, cuantas=500):
    """Recetas ordenadas por puntaje EASE, sin las que el usuario ya valoro
    o ya vio. Solo devuelve recetas con puntaje positivo (relacionadas con
    algo que reseño); recomendar() completa con top_n si faltan."""
    modelo = modelo_ease()
    positivas = items_positivos(id_lector)  # valoradas + "me tienta"
    excluir = (positivas | set(items_valorados(id_lector)) | set(items_vistos(id_lector))
               | set(items_con_senal(id_lector, "no")))

    x = np.zeros(len(modelo["recetas"]), dtype=np.float32)
    for id_receta in positivas:
        if id_receta in modelo["columna_de"]:
            x[modelo["columna_de"][id_receta]] = 1
    puntajes = x @ modelo["B"]

    elegidas = []
    for c in np.argsort(-puntajes):
        if puntajes[c] <= 0 or len(elegidas) == cuantas:
            break
        if modelo["recetas"][c] not in excluir:
            elegidas.append(modelo["recetas"][c])
    if not elegidas:
        return []

    marcas = ",".join("?" * len(elegidas))
    filas = sql_select(f"SELECT * FROM recetas WHERE id IN ({marcas})", elegidas)
    por_id = {f["id"]: f for f in filas}
    return [por_id[r] for r in elegidas]


def explicaciones(id_lector, ids_recetas):
    """Para cada receta recomendada, el titulo de la receta que el usuario
    valoro (o guardo) que mas la "empujo" en EASE: el mayor peso B[i, j].
    Sirve para mostrar "Porque te gustó ...". Devuelve {id_receta: titulo};
    las recetas sin una razon clara quedan afuera."""
    positivas = [r for r in items_positivos(id_lector)]
    if len(positivas) <= MAX_VALORADAS_COLD_START or not ids_recetas:
        return {}
    modelo = modelo_ease()
    columna_de = modelo["columna_de"]
    filas_pos = [columna_de[r] for r in positivas if r in columna_de]
    if not filas_pos:
        return {}
    por_que = {}
    for id_receta in ids_recetas:
        if id_receta not in columna_de:
            continue
        pesos = modelo["B"][filas_pos, columna_de[id_receta]]
        mejor = int(np.argmax(pesos))
        if pesos[mejor] > 0:
            por_que[id_receta] = modelo["recetas"][filas_pos[mejor]]
    if not por_que:
        return {}
    marcas = ",".join("?" * len(set(por_que.values())))
    titulos = {f["id"]: f["title"] for f in
               sql_select(f"SELECT id, title FROM recetas WHERE id IN ({marcas})", list(set(por_que.values())))}
    return {r: titulos.get(origen) for r, origen in por_que.items() if titulos.get(origen)}


def cantidad_ingredientes(ids_recetas):
    """{id_receta: cantidad de ingredientes}, para mostrar en las tarjetas."""
    if not ids_recetas:
        return {}
    marcas = ",".join("?" * len(ids_recetas))
    filas = sql_select(f"""
        SELECT recipe_id, COUNT(*) AS n FROM ingredientes
         WHERE recipe_id IN ({marcas}) GROUP BY recipe_id
    """, list(ids_recetas))
    return {f["recipe_id"]: f["n"] for f in filas}


def populares_variadas(N=12):
    """Recetas populares de categorias distintas (una por categoria), para
    que un usuario nuevo elija las que le tientan al entrar."""
    populares = top_populares(N=300)
    elegidas, categorias = [], set()
    # Primero las que tienen foto (se eligen mirando); si faltan, el resto
    for con_foto in (True, False):
        for r in populares:
            if len(elegidas) == N:
                return elegidas
            if bool(r["primary_image_url"]) == con_foto and r["category"] not in categorias:
                elegidas.append(r)
                categorias.add(r["category"])
    return elegidas


# ---------------------------------------------------------------------------
# Explorar: buscar por ingrediente y por categoria
# ---------------------------------------------------------------------------

# Categorias de food.com que no son de comida: no se muestran para explorar
CATEGORIAS_QUE_NO_SON_COMIDA = {"Household Cleaner", "Bath/Beauty", "Homeopathy/Remedies"}


def categorias_disponibles(min_recetas=10):
    """Categorias con al menos min_recetas recetas, de la mas grande a la mas chica.
    Devuelve [(categoria, cantidad), ...]."""
    filas = sql_select("""
        SELECT category, COUNT(*) AS n FROM recetas
         WHERE title IS NOT NULL AND category IS NOT NULL
         GROUP BY category HAVING COUNT(*) >= ?
         ORDER BY n DESC
    """, [min_recetas])
    return [(f["category"], f["n"]) for f in filas if f["category"] not in CATEGORIAS_QUE_NO_SON_COMIDA]


def recetas_con_ingrediente(terminos):
    """{id_receta: texto del ingrediente que coincidio} para las recetas que
    llevan alguno de los terminos (en ingles). Busca la palabra entera:
    'egg' encuentra 'eggs' pero no 'eggplant'."""
    import re
    encontradas = {}
    for termino in terminos:
        patron = re.compile(r"\b" + re.escape(termino.lower()) + r"(s|es)?\b")
        filas = sql_select("SELECT recipe_id, texto_completo FROM ingredientes WHERE LOWER(texto_completo) LIKE ?",
                           [f"%{termino.lower()}%"])
        for f in filas:
            if f["recipe_id"] not in encontradas and patron.search(f["texto_completo"].lower()):
                encontradas[f["recipe_id"]] = f["texto_completo"]
    return encontradas


def buscar_recetas(terminos=None, categoria=None, N=30):
    """Las recetas mejor valoradas (rating promedio en la base; desempata la
    cantidad de reseñas), filtradas por ingrediente y/o categoria.
    Devuelve (recetas, {id: ingrediente que coincidio})."""
    condiciones, parametros, lleva = ["recetas.title IS NOT NULL"], [], {}
    if terminos:
        lleva = recetas_con_ingrediente(terminos)
        if not lleva:
            return [], {}
        marcas = ",".join("?" * len(lleva))
        condiciones.append(f"recetas.id IN ({marcas})")
        parametros += list(lleva)
    if categoria:
        condiciones.append("recetas.category = ?")
        parametros.append(categoria)
    else:
        marcas = ",".join("?" * len(CATEGORIAS_QUE_NO_SON_COMIDA))
        condiciones.append(f"COALESCE(recetas.category, '') NOT IN ({marcas})")
        parametros += sorted(CATEGORIAS_QUE_NO_SON_COMIDA)
    parametros.append(N)
    recetas = sql_select(f"""
        SELECT recetas.*, AVG(interacciones.rating) AS promedio, COUNT(*) AS cant_resenas
          FROM recetas
          JOIN interacciones ON interacciones.id_receta = recetas.id
         WHERE {" AND ".join(condiciones)}
         GROUP BY recetas.id
         ORDER BY promedio DESC, cant_resenas DESC
         LIMIT ?
    """, parametros)
    return recetas, lleva


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
    # Cuenta lo que valoro y lo que marco "Me tienta"
    cant_items_valorados = len(items_positivos(id_lector))

    if cant_items_valorados <= MAX_VALORADAS_COLD_START:  # cold start
        rec = recomendador_top_n(id_lector)
        algoritmo = "top_n"
    else:
        rec = recomendador_ease(id_lector)
        algoritmo = "ease"

        if len(rec) < N:
            # Evitamos repetir recetas que EASE ya habia recomendado
            ids_ease = {r["id"] for r in rec}
            rec = rec + [r for r in recomendador_top_n(id_lector) if r["id"] not in ids_ease]
            algoritmo = "ease+top_n"

    rec = rec[:N]
    if registrar_vistos:
        insertar_vistos(id_lector, [r["id"] for r in rec])

    return rec, algoritmo
