"""
Recomendador en dos etapas: retrieval (generacion de candidatos) + ranking.
(La misma idea que en el proyecto de libros, adaptada a recetas.)

1) RETRIEVAL: para cada usuario se juntan candidatos de varias fuentes:
     - las mejores K_CAND_EASE recetas segun EASE
     - las mejores K_CAND_USER_KNN segun user-kNN
     - las K_CAND_RECIENTES mas reseñadas en la ventana reciente
     - hasta K_CAND_AUTOR recetas de autores que el usuario ya reseño
   Objetivo: que la receta correcta este entre los candidatos (recall).

2) RANKING: un HistGradientBoostingClassifier estima, para cada candidato,
   la probabilidad de que el usuario lo reseñe. Se recomiendan los N mas
   probables. Objetivo: el orden.

El ranking se entrena con un corte temporal DENTRO de los datos disponibles:
lo anterior a 'corte_interno' arma candidatos y variables, y las reseñas
positivas posteriores son la respuesta. Despues se vuelve a armar todo con
los datos completos para recomendar.

No se usan rating_value / rating_count de food.com: incluyen reseñas del
futuro (seria leakage). Toda la popularidad sale de 'interacciones'.
"""

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier

import config
import modelos
from base_datos import conectar

VARIABLES = [
    "ease_puntaje", "ease_puesto", "uknn_puntaje", "uknn_puesto",
    "de_ease", "de_uknn", "de_recientes", "de_autor",
    "log_resenas_receta", "log_resenas_recientes", "rating_promedio_receta",
    "recetas_resenadas_del_autor", "afinidad_categoria", "log_resenas_usuario",
]


# ===========================================================================
# Datos
# ===========================================================================

def cargar_tablas(ruta_db):
    """Interacciones (con fecha como datetime) y catalogo de recetas."""
    con = conectar(ruta_db)
    interacciones = pd.read_sql_query("SELECT id_lector, id_receta, rating, fecha FROM interacciones", con)
    recetas = pd.read_sql_query("SELECT id, category, author_id FROM recetas WHERE title IS NOT NULL", con)
    con.close()
    interacciones["fecha_dt"] = pd.to_datetime(interacciones["fecha"].str[:10], errors="coerce")
    return interacciones, recetas


def matriz_binaria(interacciones, recetas):
    """Matriz usuario x receta (1 = la reseño), solo recetas del catalogo.
    Devuelve (X, usuarios, ids_recetas)."""
    ids_recetas = sorted(recetas["id"])
    usuarios = sorted(interacciones["id_lector"].unique())
    fila_de = {u: f for f, u in enumerate(usuarios)}
    columna_de = {r: c for c, r in enumerate(ids_recetas)}
    X = np.zeros((len(usuarios), len(ids_recetas)))
    for u, r in zip(interacciones["id_lector"], interacciones["id_receta"]):
        if r in columna_de:
            X[fila_de[u], columna_de[r]] = 1
    return X, usuarios, ids_recetas


# ===========================================================================
# Retrieval: fuentes de candidatos y variables
# ===========================================================================

def preparar_fuentes(interacciones, recetas):
    """Entrena todo lo necesario para generar candidatos y variables."""
    X, usuarios, ids_recetas = matriz_binaria(interacciones, recetas)
    fin = interacciones["fecha_dt"].max()
    recientes = interacciones[interacciones["fecha_dt"] > fin - pd.Timedelta(days=config.DIAS_VENTANA_RECIENTE)]
    en_catalogo = set(ids_recetas)

    autor_de = recetas.set_index("id")["author_id"].to_dict()
    categoria_de = recetas.set_index("id")["category"].to_dict()
    recetas_por_autor = {}
    for receta, autor in autor_de.items():
        if pd.notna(autor):
            recetas_por_autor.setdefault(autor, []).append(receta)

    con_categoria = interacciones.assign(categoria=interacciones["id_receta"].map(categoria_de))
    por_categoria = con_categoria.groupby(["id_lector", "categoria"]).size()
    total_usuario = interacciones.groupby("id_lector").size()
    afinidad = (por_categoria / total_usuario.reindex(por_categoria.index.get_level_values(0)).values).to_dict()

    return {
        "X": X,
        "fila_de": {u: f for f, u in enumerate(usuarios)},
        "columna_de": {r: c for c, r in enumerate(ids_recetas)},
        "ids_recetas": ids_recetas,
        "ease": modelos.puntajes_ease(X, config.LAMBDA_EASE),
        "uknn": modelos.puntajes_user_knn(X, config.K_VECINOS),
        "resenadas": interacciones.groupby("id_lector")["id_receta"].apply(set).to_dict(),
        "recientes": [r for r in recientes["id_receta"].value_counts().index if r in en_catalogo],
        "populares": [r for r in interacciones["id_receta"].value_counts().index if r in en_catalogo],
        "resenas_receta": interacciones["id_receta"].value_counts().to_dict(),
        "resenas_recientes": recientes["id_receta"].value_counts().to_dict(),
        "rating_receta": interacciones.groupby("id_receta")["rating"].mean().to_dict(),
        "resenas_usuario": total_usuario.to_dict(),
        "autor_de": autor_de,
        "categoria_de": categoria_de,
        "recetas_por_autor": recetas_por_autor,
        "afinidad": afinidad,
    }


def mejores(puntajes, fuentes, id_lector, k):
    """Las k recetas con mayor puntaje para el usuario (sin las ya reseñadas)."""
    if id_lector not in fuentes["fila_de"]:
        return []
    f = fuentes["fila_de"][id_lector]
    p = puntajes[f].copy()
    p[fuentes["X"][f] > 0] = -np.inf
    k = min(k, len(p) - 1)
    idx = np.argpartition(-p, k)[:k]
    return [fuentes["ids_recetas"][i] for i in idx if p[i] != -np.inf]


def candidatos_con_variables(fuentes, id_lector):
    """DataFrame con una fila por candidato y las columnas de VARIABLES."""
    resenadas = fuentes["resenadas"].get(id_lector, set())
    de_ease = mejores(fuentes["ease"], fuentes, id_lector, config.K_CAND_EASE)
    de_uknn = mejores(fuentes["uknn"], fuentes, id_lector, config.K_CAND_USER_KNN)
    de_recientes = [r for r in fuentes["recientes"] if r not in resenadas][:config.K_CAND_RECIENTES]

    autores = {}
    for r in resenadas:
        a = fuentes["autor_de"].get(r)
        if pd.notna(a):
            autores[a] = autores.get(a, 0) + 1
    del_autor = {r for a in autores for r in fuentes["recetas_por_autor"].get(a, []) if r not in resenadas}
    de_autor = sorted(del_autor, key=lambda r: (-fuentes["resenas_receta"].get(r, 0), r))[:config.K_CAND_AUTOR]

    candidatos = list(dict.fromkeys(de_ease + de_uknn + de_recientes + de_autor))
    if not candidatos:
        return pd.DataFrame(columns=["id"] + VARIABLES)

    def puntajes_y_puestos(puntajes):
        valores = np.full(len(candidatos), np.nan)
        if id_lector in fuentes["fila_de"]:
            fila = puntajes[fuentes["fila_de"][id_lector]]
            for i, r in enumerate(candidatos):
                if r in fuentes["columna_de"]:
                    valores[i] = fila[fuentes["columna_de"][r]]
        return valores, pd.Series(valores).rank(ascending=False).values

    ease_p, ease_r = puntajes_y_puestos(fuentes["ease"])
    uknn_p, uknn_r = puntajes_y_puestos(fuentes["uknn"])
    s_ease, s_uknn, s_rec, s_aut = set(de_ease), set(de_uknn), set(de_recientes), set(de_autor)

    return pd.DataFrame({
        "id": candidatos,
        "ease_puntaje": ease_p,
        "ease_puesto": ease_r,
        "uknn_puntaje": uknn_p,
        "uknn_puesto": uknn_r,
        "de_ease": [r in s_ease for r in candidatos],
        "de_uknn": [r in s_uknn for r in candidatos],
        "de_recientes": [r in s_rec for r in candidatos],
        "de_autor": [r in s_aut for r in candidatos],
        "log_resenas_receta": [np.log1p(fuentes["resenas_receta"].get(r, 0)) for r in candidatos],
        "log_resenas_recientes": [np.log1p(fuentes["resenas_recientes"].get(r, 0)) for r in candidatos],
        "rating_promedio_receta": [fuentes["rating_receta"].get(r, np.nan) for r in candidatos],
        "recetas_resenadas_del_autor": [autores.get(fuentes["autor_de"].get(r), 0) for r in candidatos],
        "afinidad_categoria": [fuentes["afinidad"].get((id_lector, fuentes["categoria_de"].get(r)), 0.0)
                               for r in candidatos],
        "log_resenas_usuario": np.log1p(fuentes["resenas_usuario"].get(id_lector, 0)),
    })


# ===========================================================================
# Ranking
# ===========================================================================

def entrenar_ranker(interacciones, recetas, corte_interno, rating_positivo=config.RATING_POSITIVO,
                    min_resenas=config.MIN_QUE_QUEDAN, semilla=config.SEMILLA):
    """Entrena el modelo de ranking con un corte temporal dentro de los datos.
    Devuelve (modelo, filas de entrenamiento, positivos)."""
    corte = pd.Timestamp(corte_interno)
    pasado = interacciones[~(interacciones["fecha_dt"] >= corte)]
    futuro = interacciones[(interacciones["fecha_dt"] >= corte) & (interacciones["rating"] >= rating_positivo)]
    fuentes = preparar_fuentes(pasado, recetas)

    previas = pasado.groupby("id_lector").size()
    con_pasado = set(previas[previas >= min_resenas].index)
    respuestas = futuro[futuro["id_lector"].isin(con_pasado)].groupby("id_lector")["id_receta"].apply(set).to_dict()

    tablas = []
    for id_lector in sorted(respuestas):
        tabla = candidatos_con_variables(fuentes, id_lector)
        tabla["resenada"] = tabla["id"].isin(respuestas[id_lector])
        tablas.append(tabla)
    entrenamiento = pd.concat(tablas, ignore_index=True)

    modelo = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, max_leaf_nodes=31,
                                            random_state=semilla)
    modelo.fit(entrenamiento[VARIABLES].astype(float), entrenamiento["resenada"].astype(int))
    return modelo, len(entrenamiento), int(entrenamiento["resenada"].sum())


def crear_dos_etapas(ruta_db, n=config.N_RECOMENDACIONES, corte_interno=config.CORTE_RANKER):
    """Estrategia en dos etapas: recibe id_lector y devuelve [{"id": ...}, ...]."""
    interacciones, recetas = cargar_tablas(ruta_db)
    ranker, filas, positivos = entrenar_ranker(interacciones, recetas, corte_interno)
    print(f"    ranker entrenado con {filas} pares usuario-receta ({positivos} reseñadas), corte interno {corte_interno}")
    fuentes = preparar_fuentes(interacciones, recetas)

    def estrategia(id_lector):
        tabla = candidatos_con_variables(fuentes, id_lector)
        if tabla.empty:
            elegidas = []
        else:
            tabla["probabilidad"] = ranker.predict_proba(tabla[VARIABLES].astype(float))[:, 1]
            elegidas = tabla.sort_values(["probabilidad", "id"], ascending=[False, True])["id"].head(n).tolist()
        # si faltan, completar con las mas reseñadas que el usuario no reseño
        resenadas = fuentes["resenadas"].get(id_lector, set())
        for r in fuentes["populares"]:
            if len(elegidas) >= n:
                break
            if r not in resenadas and r not in elegidas:
                elegidas.append(r)
        return [{"id": r} for r in elegidas]

    return estrategia


def crear_populares_recientes(ruta_db, n=config.N_RECOMENDACIONES):
    """Baseline: las recetas mas reseñadas en la ventana reciente."""
    interacciones, recetas = cargar_tablas(ruta_db)
    fuentes = preparar_fuentes(interacciones, recetas)
    lista = fuentes["recientes"] + [r for r in fuentes["populares"] if r not in set(fuentes["recientes"])]

    def estrategia(id_lector):
        resenadas = fuentes["resenadas"].get(id_lector, set())
        return [{"id": r} for r in lista if r not in resenadas][:n]

    return estrategia
