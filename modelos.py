"""
Modelos de filtrado colaborativo.

Los dos trabajan con la matriz usuario x receta en version BINARIA:
1 = el usuario reseño la receta, 0 = no. Se usa binaria porque el 97% de
las reseñas tiene 4 o 5 estrellas: el rating casi no distingue gustos, y
la señal util es QUE recetas reseño cada usuario (feedback implicito).

  - user-kNN: busca los k usuarios mas parecidos (similitud coseno) y
    recomienda lo que reseñaron ellos. "A usuarios como vos les gusto...".

  - EASE (Steck, 2019, "Embarrassingly Shallow Autoencoders for Sparse
    Data"): aprende un peso para cada par de recetas (cuanto "empuja" haber
    reseñado la receta i a reseñar la receta j) resolviendo una regresion
    ridge con formula cerrada. Con 1.855 recetas es invertir una matriz de
    1.855 x 1.855: tarda un segundo.

Cada modelo devuelve una matriz de puntajes (usuarios x recetas). Despues
crear_estrategia() la convierte en una funcion id_lector -> recetas, con la
misma forma que las estrategias de recomendador.py, para poder evaluarlas
juntas en evaluacion.py.
"""

import numpy as np

import recomendador
from base_datos import conectar


def cargar_matriz(ruta_db):
    """Arma la matriz binaria usuario x receta con la tabla 'interacciones'.
    Solo entran las recetas del catalogo (con titulo), que son las unicas
    que se pueden recomendar.
    Devuelve (X, usuarios, recetas): usuarios[f] es el id de la fila f y
    recetas[c] el id de la columna c."""
    con = conectar(ruta_db)
    recetas = [r for (r,) in con.execute("SELECT id FROM recetas WHERE title IS NOT NULL ORDER BY id")]
    interacciones = con.execute("SELECT id_lector, id_receta FROM interacciones").fetchall()
    con.close()

    usuarios = sorted({u for u, _ in interacciones})
    fila_de = {u: f for f, u in enumerate(usuarios)}
    columna_de = {r: c for c, r in enumerate(recetas)}

    X = np.zeros((len(usuarios), len(recetas)))
    for u, r in interacciones:
        if r in columna_de:
            X[fila_de[u], columna_de[r]] = 1
    return X, usuarios, recetas


def quedarse_con_los_k_mayores(matriz, k):
    """En cada fila deja los k valores mas altos y pone 0 en el resto."""
    resultado = matriz.copy()
    if k < matriz.shape[1]:
        posiciones_a_borrar = np.argsort(-matriz, axis=1)[:, k:]
        np.put_along_axis(resultado, posiciones_a_borrar, 0, axis=1)
    return resultado


def puntajes_user_knn(X, k):
    """user-kNN con similitud coseno.
    puntaje(usuario, receta) = suma de las similitudes de los k vecinos
    del usuario que reseñaron esa receta."""
    largos = np.sqrt(X.sum(axis=1))
    largos[largos == 0] = 1  # evita dividir por cero
    similitud = (X @ X.T) / np.outer(largos, largos)
    np.fill_diagonal(similitud, 0)  # un usuario no es vecino de si mismo
    vecinos = quedarse_con_los_k_mayores(similitud, k)
    return vecinos @ X


def puntajes_ease(X, lambda_):
    """EASE: B = pesos receta x receta, con diagonal en 0 (una receta no
    puede recomendarse a si misma). lambda_ es la regularizacion: cuanto
    mas alta, mas "suaves" quedan los pesos."""
    return X @ recomendador.pesos_ease(X, lambda_)  # la misma cuenta que usa la pagina


def crear_estrategia(puntajes, X, usuarios, recetas):
    """Convierte una matriz de puntajes en una estrategia: una funcion que
    recibe id_lector y devuelve las recetas ordenadas de mejor a peor
    (como lista de {"id": ...}), sin las que el usuario ya reseño.
    Un usuario que no esta en la matriz (cold start) recibe popularidad."""
    fila_de = {u: f for f, u in enumerate(usuarios)}

    def estrategia(id_lector):
        if id_lector not in fila_de:
            return recomendador.recomendador_top_n(id_lector)
        f = fila_de[id_lector]
        p = puntajes[f].copy()
        p[X[f] > 0] = -np.inf  # no recomendar lo que ya reseño
        orden = np.argsort(-p)
        return [{"id": recetas[c]} for c in orden if p[c] != -np.inf]

    return estrategia
