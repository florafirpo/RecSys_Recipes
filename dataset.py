"""
Armado de las bases que usa el recomendador.

1) armar_base_app: arma recetas_app.db (liviana, para PythonAnywhere) con el
   subconjunto de usuarios y recetas que eligio el filtrado de matriz.py.

   OJO con los ids: en food_scraping.db hay DOS numeraciones de recetas:
     - recetas.id            -> numero interno que SQLite le puso a cada fila.
     - comentarios.recipe_id -> el id REAL de food.com (el numero al final de la URL).
   Aca cada receta se busca por el numero final de su URL y se guarda con ese
   id real, asi interacciones.id_receta y recetas.id hablan del mismo numero.

2) separar_train_test: a cada usuario le esconde algunas reviews positivas
   (van a recetas_test.db) y el resto queda en recetas_train.db. El
   recomendador aprende solo con train y despues medimos si recomienda las
   recetas escondidas.
"""

import os
import random
import shutil
import sqlite3

import config
from base_datos import conectar, consulta_por_lotes, id_food_desde_url, leer_ids_del_csv


# ===========================================================================
# 1) Base de la aplicacion
# ===========================================================================

def crear_tablas_app(con):
    """Crea las tablas vacias de recetas_app.db."""
    con.execute("""
        CREATE TABLE recetas (
            id INTEGER PRIMARY KEY,
            url TEXT,
            title TEXT,
            description TEXT,
            category TEXT,
            rating_value REAL,
            rating_count INTEGER,
            author_id INTEGER,
            author_name TEXT,
            primary_image_url TEXT
        )
    """)
    con.execute("""
        CREATE TABLE usuarios (
            member_id INTEGER PRIMARY KEY,
            username TEXT,
            nombre TEXT,
            bio TEXT,
            ubicacion TEXT,
            rating_promedio REAL
        )
    """)
    con.execute("""
        CREATE TABLE interacciones (
            id_lector INTEGER,
            id_receta INTEGER,
            rating INTEGER,
            fecha TEXT,
            PRIMARY KEY (id_lector, id_receta)
        )
    """)
    con.execute("""
        CREATE TABLE ingredientes (
            recipe_id INTEGER,
            orden INTEGER,
            texto_completo TEXT,
            nombre_ingrediente TEXT
        )
    """)
    con.execute("""
        CREATE TABLE vistos (
            id_lector INTEGER,
            id_receta INTEGER,
            fecha TEXT,
            PRIMARY KEY (id_lector, id_receta)
        )
    """)
    con.commit()


def mapear_ids_reales(origen, items_set):
    """Devuelve {id real de food.com: fila interna de 'recetas'} para las
    recetas del recorte, buscandolas por el numero final de su URL."""
    print("Buscando cada receta por el numero final de su URL...")
    interno_por_food = {}
    repetidos = 0
    for fila_id, url, scraped_ok in origen.execute("SELECT id, url, scraped_ok FROM recetas"):
        food_id = id_food_desde_url(url)
        if food_id is None or food_id not in items_set:
            continue
        if food_id in interno_por_food:
            repetidos += 1
            # si hay dos filas con la misma URL final, preferimos la ya scrapeada
            if scraped_ok != 1:
                continue
        interno_por_food[food_id] = fila_id

    print(f"  Encontradas: {len(interno_por_food)} de {len(items_set)}")
    if repetidos:
        print(f"  Aviso: {repetidos} ids aparecian en mas de una URL.")
    faltan = items_set - set(interno_por_food)
    if faltan:
        print(f"  Aviso: {len(faltan)} recetas del recorte no estan en 'recetas' (primeras 10: {sorted(faltan)[:10]}).")
    return interno_por_food


def copiar_recetas(origen, destino, interno_por_food):
    """Copia las recetas del recorte (sin las columnas pesadas), con el id real."""
    print("Copiando recetas...")
    food_por_interno = {v: k for k, v in interno_por_food.items()}
    filas = consulta_por_lotes(origen, """
        SELECT id, url, title, description, category, rating_value,
               rating_count, author_id, author_name, primary_image_url
        FROM recetas WHERE id IN ({ph})
    """, interno_por_food.values())
    destino.executemany(
        "INSERT INTO recetas VALUES (?,?,?,?,?,?,?,?,?,?)",
        [(food_por_interno[f[0]],) + tuple(f[1:]) for f in filas]
    )
    destino.commit()
    print(f"  {len(filas)} recetas copiadas.")


def copiar_usuarios(origen, destino, usuarios_ids):
    """Copia los perfiles de los usuarios del recorte (si existe la tabla 'usuarios')."""
    print("Copiando usuarios...")
    try:
        filas = consulta_por_lotes(origen, """
            SELECT member_id, username, nombre, bio, ubicacion, rating_promedio
            FROM usuarios WHERE member_id IN ({ph})
        """, usuarios_ids)
        destino.executemany("INSERT INTO usuarios VALUES (?,?,?,?,?,?)", [tuple(f) for f in filas])
        destino.commit()
        print(f"  {len(filas)} usuarios copiados (con perfil scrapeado).")
    except sqlite3.OperationalError:
        print("  Aviso: no encontre la tabla 'usuarios' en food_scraping.db -- se omite, no es obligatoria.")


def copiar_interacciones(origen, destino, usuarios_ids, items_set):
    """Copia las reviews reales (de 'comentarios') entre esos usuarios y esas
    recetas. comentarios.recipe_id ya es el id real de food.com."""
    print("Copiando interacciones (comentarios reales entre ese subconjunto)...")
    usuarios_set = set(usuarios_ids)
    n = 0
    for member_id, recipe_id, rating, submitted in origen.execute(
            "SELECT member_id, recipe_id, rating, submitted FROM comentarios"):
        if rating is None or rating <= 0:
            continue  # reseña sin estrellas: no es un rating (misma regla que matriz.py)
        if member_id in usuarios_set and recipe_id in items_set:
            destino.execute("INSERT OR IGNORE INTO interacciones VALUES (?,?,?,?)",
                            (member_id, recipe_id, rating, submitted))
            n += 1
    destino.commit()
    guardadas = destino.execute("SELECT COUNT(*) FROM interacciones").fetchone()[0]
    print(f"  {n} interacciones leidas, {guardadas} guardadas.")


def copiar_ingredientes(origen, destino, interno_por_food):
    """Copia los ingredientes de esas recetas. En el origen usan el id interno;
    aca se pasan al id real."""
    print("Copiando ingredientes de esas recetas...")
    food_por_interno = {v: k for k, v in interno_por_food.items()}
    filas = consulta_por_lotes(origen, """
        SELECT recipe_id, orden, texto_completo, nombre_ingrediente
        FROM ingredientes WHERE recipe_id IN ({ph})
    """, interno_por_food.values())
    destino.executemany(
        "INSERT INTO ingredientes VALUES (?,?,?,?)",
        [(food_por_interno[f[0]],) + tuple(f[1:]) for f in filas]
    )
    destino.commit()
    print(f"  {len(filas)} filas de ingredientes copiadas.")


def chequear_base_app(destino):
    """Imprime los controles de calidad de la base nueva."""
    print("\nChequeos:")
    n_recetas = destino.execute("SELECT COUNT(*) FROM recetas").fetchone()[0]
    sin_receta = destino.execute(
        "SELECT COUNT(*) FROM interacciones WHERE id_receta NOT IN (SELECT id FROM recetas)"
    ).fetchone()[0]
    total_ints = destino.execute("SELECT COUNT(*) FROM interacciones").fetchone()[0]
    print(f"  Recetas en la base nueva: {n_recetas}")
    print(f"  Interacciones sobre recetas sin ficha: {sin_receta} de {total_ints}")
    desalineadas = sum(1 for rid, url in destino.execute("SELECT id, url FROM recetas")
                       if id_food_desde_url(url) != rid)
    print(f"  Recetas cuyo id no coincide con el numero final de su URL: {desalineadas} (debe ser 0)")


def armar_base_app(db_origen=config.DB_SCRAPING, db_destino=config.DB_APP,
                   csv_usuarios=config.CSV_USUARIOS, csv_items=config.CSV_ITEMS):
    """Arma recetas_app.db desde cero a partir de food_scraping.db y de los
    CSV de indices que exporta matriz.py. Si ya habia una recetas_app.db, la
    guarda como recetas_app_anterior.db (por si hay que volver atras)."""
    if os.path.exists(db_destino):
        respaldo = db_destino.replace(".db", "_anterior.db")
        shutil.copyfile(db_destino, respaldo)
        os.remove(db_destino)
        print(f"La base anterior quedo guardada en {os.path.basename(respaldo)}")

    usuarios_ids = leer_ids_del_csv(csv_usuarios, "member_id")
    items_ids = leer_ids_del_csv(csv_items, "recipe_id")
    items_set = set(items_ids)
    print(f"Usuarios a incluir: {len(usuarios_ids)}")
    print(f"Recetas a incluir (ids reales de food.com): {len(items_ids)}")

    origen = conectar(db_origen)
    destino = conectar(db_destino)

    crear_tablas_app(destino)
    interno_por_food = mapear_ids_reales(origen, items_set)
    copiar_recetas(origen, destino, interno_por_food)
    copiar_usuarios(origen, destino, usuarios_ids)
    copiar_interacciones(origen, destino, usuarios_ids, items_set)
    copiar_ingredientes(origen, destino, interno_por_food)
    chequear_base_app(destino)

    origen.close()
    destino.close()
    tamanio_mb = os.path.getsize(db_destino) / (1024 ** 2)
    print(f"\nListo. '{db_destino}' creado, pesa {tamanio_mb:.1f} MB.")


# ===========================================================================
# 2) Separacion train / test
# ===========================================================================

def separar_train_test(db_app=config.DB_APP, db_train=config.DB_TRAIN, db_test=config.DB_TEST,
                       fraccion_test=config.FRACCION_TEST,
                       min_que_quedan=config.MIN_QUE_QUEDAN,
                       rating_positivo=config.RATING_POSITIVO,
                       semilla=config.SEMILLA):
    """Separa la base en train y test, por usuario.

    - Copia db_app a db_train (la original no se toca).
    - A cada usuario le saca al azar el 'fraccion_test' de sus reviews (por
      ejemplo 20%: un usuario con 50 reviews deja 10 en test), eligiendo solo
      entre las positivas (rating >= rating_positivo), porque la pregunta es
      "¿le recomendamos algo que le gusto?". Todo usuario con reviews
      suficientes deja al menos 1 en test.
    - Solo reserva recetas que estan en el catalogo ('recetas' con titulo):
      las demas el recomendador nunca las podria sugerir.
    - Le deja al menos 'min_que_quedan' reviews en train a cada usuario.
    - Vacia 'vistos' y 'lote_actual' en train, para que la evaluacion arranque limpia.
    """
    shutil.copyfile(db_app, db_train)
    if os.path.exists(db_test):
        os.remove(db_test)

    azar = random.Random(semilla)

    train = conectar(db_train)
    test = conectar(db_test)
    test.execute("""
        CREATE TABLE interacciones (
            id_lector INTEGER,
            id_receta INTEGER,
            rating INTEGER,
            fecha TEXT,
            PRIMARY KEY (id_lector, id_receta)
        )
    """)

    usuarios = [fila[0] for fila in train.execute(
        "SELECT DISTINCT id_lector FROM interacciones ORDER BY id_lector"
    )]

    reservadas_total = 0
    usuarios_sin_reserva = 0

    for id_lector in usuarios:
        total = train.execute(
            "SELECT COUNT(*) FROM interacciones WHERE id_lector = ?", [id_lector]
        ).fetchone()[0]
        positivas = train.execute(
            "SELECT id_lector, id_receta, rating, fecha FROM interacciones "
            "WHERE id_lector = ? AND rating >= ? "
            "AND id_receta IN (SELECT id FROM recetas WHERE title IS NOT NULL) "
            "ORDER BY id_receta",
            [id_lector, rating_positivo],
        ).fetchall()

        cantidad = max(1, round(fraccion_test * total))
        cantidad = min(cantidad, len(positivas), total - min_que_quedan)
        if cantidad <= 0:
            usuarios_sin_reserva += 1
            continue

        reservadas = azar.sample(positivas, cantidad)
        test.executemany("INSERT INTO interacciones VALUES (?, ?, ?, ?)", reservadas)
        train.executemany(
            "DELETE FROM interacciones WHERE id_lector = ? AND id_receta = ?",
            [(r[0], r[1]) for r in reservadas],
        )
        reservadas_total += cantidad

    # La evaluacion tiene que arrancar sin recetas "ya vistas"
    train.execute("DELETE FROM vistos")
    train.execute("DROP TABLE IF EXISTS lote_actual")

    train.commit()
    test.commit()
    train.close()
    test.close()

    print(f"Usuarios: {len(usuarios)}")
    print(f"Reviews reservadas para test: {reservadas_total}")
    if usuarios_sin_reserva:
        print(f"Usuarios sin reviews reservadas (pocas reviews positivas): {usuarios_sin_reserva}")
    print(f"Guardado en {os.path.basename(db_train)} y {os.path.basename(db_test)}")


def separar_train_test_temporal(fecha_corte, db_app=config.DB_APP, db_train=config.DB_TRAIN, db_test=config.DB_TEST,
                                min_en_train=config.MIN_QUE_QUEDAN, rating_positivo=config.RATING_POSITIVO):
    """Corte global por fecha: el modelo aprende con el pasado y se lo evalua con el futuro.

    - train: las reseñas ANTERIORES a fecha_corte ("aaaa-mm-dd").
    - test : las reseñas positivas desde fecha_corte, de recetas del catalogo y
             de usuarios con al menos min_en_train reseñas antes del corte.
    - Todas las reseñas posteriores al corte salen de train, aunque no vayan a
      test: si no, el modelo veria el futuro de otros usuarios.
    Las fechas vienen como "2008-03-14T10:22:05Z": alcanza con comparar los
    primeros 10 caracteres como texto.
    """
    shutil.copyfile(db_app, db_train)
    if os.path.exists(db_test):
        os.remove(db_test)

    train = conectar(db_train)
    test = conectar(db_test)
    test.execute("""
        CREATE TABLE interacciones (
            id_lector INTEGER,
            id_receta INTEGER,
            rating INTEGER,
            fecha TEXT,
            PRIMARY KEY (id_lector, id_receta)
        )
    """)

    filas = train.execute("SELECT id_lector, id_receta, rating, fecha FROM interacciones").fetchall()
    futuras = [f for f in filas if f[3] and f[3][:10] >= fecha_corte]
    previas = {}
    for f in filas:
        if not (f[3] and f[3][:10] >= fecha_corte):
            previas[f[0]] = previas.get(f[0], 0) + 1
    catalogo = {r for (r,) in train.execute("SELECT id FROM recetas WHERE title IS NOT NULL")}
    para_test = [f for f in futuras
                 if previas.get(f[0], 0) >= min_en_train and f[2] is not None
                 and f[2] >= rating_positivo and f[1] in catalogo]

    test.executemany("INSERT INTO interacciones VALUES (?, ?, ?, ?)", para_test)
    train.executemany("DELETE FROM interacciones WHERE id_lector = ? AND id_receta = ?",
                      [(f[0], f[1]) for f in futuras])
    train.execute("DELETE FROM vistos")
    train.execute("DROP TABLE IF EXISTS lote_actual")
    train.commit()
    test.commit()
    train.close()
    test.close()

    print(f"Corte: {fecha_corte}")
    print(f"Reseñas posteriores al corte (salen de train): {len(futuras)}")
    print(f"Reseñas en test (positivas, de usuarios con pasado): {len(para_test)}")
    print(f"Usuarios en test: {len({f[0] for f in para_test})}")
    print(f"Guardado en {os.path.basename(db_train)} y {os.path.basename(db_test)}")
