"""
Ajuste de hiperparametros de los modelos colaborativos (k de user-kNN y
lambda de EASE) con una VALIDACION sacada de train.

¿Por que no elegirlos directo mirando test? Porque si probamos 10 valores
contra test y nos quedamos con el mejor, el numero de test deja de ser una
medicion honesta: lo elegimos justamente porque le fue bien ahi. Por eso
test se reserva para medir UNA vez, al final.

Como se arma la validacion (todo dentro de recetas_train.db):
  - modo temporal (--temporal AAAA-MM-DD): lo anterior a esa fecha es
    "train interno" y las reseñas positivas posteriores son validacion.
    Es el modo que corresponde si el test se armo con corte temporal.
  - modo al azar (sin fecha): a cada usuario se le esconde el 20% de sus
    reseñas positivas, igual que en dataset.separar_train_test.

Para que sea rapido, todo se calcula con numpy en memoria: no se crean bases
nuevas. Las metricas son las mismas que en evaluacion.py.
"""

import random
from collections import defaultdict

import numpy as np

import config
import modelos
from base_datos import conectar

GRILLA_K = (5, 10, 20, 30, 50, 75, 100, 150, 200, 300)
GRILLA_LAMBDA = (10, 50, 100, 200, 300, 500, 750, 1000, 2000, 5000)


def cargar_train(db_train):
    """Devuelve (recetas del catalogo, lista de reseñas (usuario, receta, rating, fecha))."""
    con = conectar(db_train)
    recetas = [r for (r,) in con.execute("SELECT id FROM recetas WHERE title IS NOT NULL ORDER BY id")]
    resenas = con.execute("SELECT id_lector, id_receta, rating, fecha FROM interacciones").fetchall()
    con.close()
    return recetas, resenas


def validacion_temporal(resenas, en_catalogo, fecha_corte,
                        min_en_train=config.MIN_QUE_QUEDAN, rating_positivo=config.RATING_POSITIVO):
    """Separa por fecha. Devuelve (reseñas de train interno, {usuario: set(recetas de validacion)})."""
    antes = [r for r in resenas if (r[3] or "")[:10] < fecha_corte]
    despues = [r for r in resenas if (r[3] or "")[:10] >= fecha_corte]

    cuantas_antes = defaultdict(int)
    for u, _, _, _ in antes:
        cuantas_antes[u] += 1

    validacion = defaultdict(set)
    for u, receta, rating, _ in despues:
        if rating >= rating_positivo and receta in en_catalogo and cuantas_antes[u] >= min_en_train:
            validacion[u].add(receta)
    return antes, dict(validacion)


def validacion_al_azar(resenas, en_catalogo, fraccion=config.FRACCION_TEST,
                       min_que_quedan=config.MIN_QUE_QUEDAN,
                       rating_positivo=config.RATING_POSITIVO, semilla=config.SEMILLA):
    """A cada usuario le esconde el 20% de sus positivas. Mismo criterio que el split de test."""
    azar = random.Random(semilla)
    por_usuario = defaultdict(list)
    for r in resenas:
        por_usuario[r[0]].append(r)

    train, validacion = [], {}
    for u in sorted(por_usuario):
        suyas = por_usuario[u]
        positivas = [r for r in suyas if r[2] >= rating_positivo and r[1] in en_catalogo]
        cantidad = max(1, round(fraccion * len(suyas)))
        cantidad = min(cantidad, len(positivas), len(suyas) - min_que_quedan)
        escondidas = set()
        if cantidad > 0:
            escondidas = {r[1] for r in azar.sample(positivas, cantidad)}
            validacion[u] = escondidas
        train.extend(r for r in suyas if r[1] not in escondidas)
    return train, validacion


def matriz_binaria(resenas, usuarios, recetas):
    fila_de = {u: f for f, u in enumerate(usuarios)}
    columna_de = {r: c for c, r in enumerate(recetas)}
    X = np.zeros((len(usuarios), len(recetas)))
    for u, receta, _, _ in resenas:
        if receta in columna_de:
            X[fila_de[u], columna_de[receta]] = 1
    return X


def medir(puntajes, X, usuarios, recetas, validacion, n=config.N_RECOMENDACIONES):
    """precision@N y MRR promedio sobre los usuarios de validacion."""
    fila_de = {u: f for f, u in enumerate(usuarios)}
    precision, mrr = [], []
    for u, escondidas in validacion.items():
        f = fila_de[u]
        p = puntajes[f].copy()
        p[X[f] > 0] = -np.inf  # no recomendar lo que ya reseño
        mejores = np.argpartition(-p, n)[:n]
        mejores = mejores[np.argsort(-p[mejores])]
        aciertos = [i for i, c in enumerate(mejores) if recetas[c] in escondidas]
        precision.append(len(aciertos) / n)
        mrr.append(1 / (aciertos[0] + 1) if aciertos else 0.0)
    return float(np.mean(precision)), float(np.mean(mrr))


def popularidad(X):
    """Linea de referencia: la misma lista de mas reseñadas para todos."""
    return np.tile(X.sum(axis=0), (X.shape[0], 1))


def ajustar(db_train=config.DB_TRAIN, fecha_corte=None, grilla_k=GRILLA_K, grilla_lambda=GRILLA_LAMBDA):
    """Prueba la grilla y muestra la tabla. Devuelve (mejor_k, mejor_lambda, resultados)."""
    recetas, resenas = cargar_train(db_train)
    en_catalogo = set(recetas)
    if fecha_corte:
        train, validacion = validacion_temporal(resenas, en_catalogo, fecha_corte)
        print(f"Validacion temporal: train interno antes de {fecha_corte}")
    else:
        train, validacion = validacion_al_azar(resenas, en_catalogo)
        print("Validacion al azar: 20% de las positivas de cada usuario")

    usuarios = sorted({r[0] for r in train})
    X = matriz_binaria(train, usuarios, recetas)
    print(f"  {len(train)} reseñas de train interno, {sum(len(v) for v in validacion.values())} "
          f"de validacion, {len(validacion)} usuarios\n")

    prec_pop, mrr_pop = medir(popularidad(X), X, usuarios, recetas, validacion)
    print(f"Referencia, popularidad: precision@10 = {prec_pop:.4f}   MRR = {mrr_pop:.4f}\n")

    resultados = {"user-kNN": {}, "EASE": {}}
    print("user-kNN")
    print("       k  precision@10      MRR")
    for k in grilla_k:
        if k >= len(usuarios):
            continue
        prec, mrr = medir(modelos.puntajes_user_knn(X, k), X, usuarios, recetas, validacion)
        resultados["user-kNN"][k] = (prec, mrr)
        print(f"  {k:6d}  {prec:12.4f}  {mrr:7.4f}")

    print("\nEASE")
    print("  lambda  precision@10      MRR")
    for lambda_ in grilla_lambda:
        prec, mrr = medir(modelos.puntajes_ease(X, lambda_), X, usuarios, recetas, validacion)
        resultados["EASE"][lambda_] = (prec, mrr)
        print(f"  {lambda_:6d}  {prec:12.4f}  {mrr:7.4f}")

    # El mejor es el de mayor precision; si empatan, el de mayor MRR
    mejor_k = max(resultados["user-kNN"], key=lambda k: resultados["user-kNN"][k])
    mejor_lambda = max(resultados["EASE"], key=lambda l: resultados["EASE"][l])
    print(f"\nMejor k = {mejor_k}   mejor lambda = {mejor_lambda}")
    print(f"(en config.py hoy: K_VECINOS = {config.K_VECINOS}, LAMBDA_EASE = {config.LAMBDA_EASE})")
    return mejor_k, mejor_lambda, resultados
