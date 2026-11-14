"""
¿Qué modelo conviene según cuánto sabemos del usuario?

Todos los usuarios de la base tienen 40 reseñas o más (por el p-core), así
que la evaluación normal nunca prueba el caso de un usuario nuevo. Este
script lo simula: a cada usuario de test le deja solo sus ultimas k reseñas
de train, como si fuera todo lo que el sistema sabe de el, y mide cada
modelo con NDCG@10 sobre su test.

Detalles:
  - Pensado para el split TEMPORAL (train antes del corte, test despues).
  - Los demas usuarios conservan su historial completo: solo se "achica" al
    usuario que se evalua. Los pesos de EASE se entrenan una vez con todo
    train; test no se usa para entrenar nada.
  - No se recomiendan recetas que el usuario ya reseñó antes del corte (todo
    su historial de train, no solo las k conocidas). Si no, los modelos
    gastarian lugares en recetas que nunca pueden ser acierto en test: es el
    mismo criterio de la evaluacion normal.
  - Para cada k se comparan EASE y user-kNN contra popularidad con un
    intervalo de confianza del 95 % por bootstrap pareado (como evaluacion.py).

Uso: python main.py actividad   (despues de python main.py split --temporal ...)
"""

import math
import random
from collections import defaultdict

import numpy as np

import config
import recomendador
from base_datos import conectar

VALORES_K = (0, 1, 2, 3, 4, 5, 6, 8, 10, 15, 20, 30, 50)
N = config.N_RECOMENDACIONES


def cargar(db_train=config.DB_TRAIN, db_test=config.DB_TEST):
    con = conectar(db_train)
    recetas = [r for (r,) in con.execute("SELECT id FROM recetas WHERE title IS NOT NULL ORDER BY id")]
    train = con.execute("SELECT id_lector, id_receta, rating, fecha FROM interacciones").fetchall()
    con.close()
    con = conectar(db_test)
    test = con.execute("SELECT id_lector, id_receta, rating FROM interacciones").fetchall()
    con.close()
    return recetas, train, test


def ndcg(recomendadas, reservadas, n=N):
    dcg = sum(1 / math.log2(i + 2) for i, r in enumerate(recomendadas) if r in reservadas)
    idcg = sum(1 / math.log2(i + 2) for i in range(min(len(reservadas), n)))
    return dcg / idcg


def top_n(puntajes, excluir_cols, n=N):
    p = puntajes.astype(float).copy()
    if excluir_cols:
        p[list(excluir_cols)] = -np.inf
    mejores = np.argpartition(-p, n)[:n]
    return mejores[np.argsort(-p[mejores])]


def intervalo(dif, repeticiones=2000, semilla=config.SEMILLA):
    """Media de la diferencia y su IC 95 % por bootstrap sobre usuarios."""
    rng = np.random.default_rng(semilla)
    dif = np.asarray(dif)
    medias = [dif[rng.integers(0, len(dif), len(dif))].mean() for _ in range(repeticiones)]
    return dif.mean(), np.percentile(medias, 2.5), np.percentile(medias, 97.5)


def simular(valores_k=VALORES_K, k_vecinos=config.K_VECINOS, lambda_ease=config.LAMBDA_EASE):
    recetas, train, test = cargar()
    columna_de = {r: c for c, r in enumerate(recetas)}
    usuarios = sorted({u for u, _, _, _ in train})
    fila_de = {u: f for f, u in enumerate(usuarios)}

    X = np.zeros((len(usuarios), len(recetas)))
    popularidad = np.zeros(len(recetas))
    historial = defaultdict(list)  # usuario -> [(fecha, columna)]
    for u, receta, rating, fecha in train:
        if receta in columna_de:
            c = columna_de[receta]
            X[fila_de[u], c] = 1
            popularidad[c] += rating          # igual que top_n: suma de ratings
            historial[u].append((fecha or "", c))

    reservadas = defaultdict(set)
    for u, receta, rating in test:
        if rating >= config.RATING_POSITIVO and receta in columna_de and u in fila_de:
            reservadas[u].add(columna_de[receta])
    evaluables = sorted(reservadas)

    B = recomendador.pesos_ease(X, lambda_ease)
    normas = np.linalg.norm(X, axis=1)

    resultados = []
    for k in valores_k:
        filas = {"popularidad": [], "user-kNN": [], "EASE": []}
        for u in evaluables:
            hist = sorted(historial[u])
            if len(hist) < k:
                continue  # el usuario no tiene k reseñas para conservar
            conocidas = {c for _, c in hist[-k:]} if k else set()
            ya_resenadas = {c for _, c in hist}
            filas["popularidad"].append(ndcg(top_n(popularidad, ya_resenadas), reservadas[u]))
            if k == 0:
                continue  # sin historial, los modelos personalizados no tienen de donde partir
            x = np.zeros(len(recetas))
            x[list(conocidas)] = 1
            # EASE: suma de las filas de B de lo que conoce
            filas["EASE"].append(ndcg(top_n(x @ B, ya_resenadas), reservadas[u]))
            # user-kNN: similitud coseno contra los demas usuarios (sin el mismo)
            sim = (X @ x) / (normas * np.linalg.norm(x) + 1e-12)
            sim[fila_de[u]] = 0
            vecinos = np.argpartition(-sim, k_vecinos)[:k_vecinos]
            filas["user-kNN"].append(ndcg(top_n(sim[vecinos] @ X[vecinos], ya_resenadas), reservadas[u]))

        fila = {"k": k, "usuarios": len(filas["popularidad"]),
                "popularidad": float(np.mean(filas["popularidad"]))}
        for modelo in ("EASE", "user-kNN"):
            if filas[modelo]:
                fila[modelo] = float(np.mean(filas[modelo]))
                fila[modelo + "_ic"] = intervalo(np.array(filas[modelo]) - np.array(filas["popularidad"]))
        resultados.append(fila)
    return resultados


def mostrar(resultados):
    def comparar(ic):
        m, lo, hi = ic
        marca = "mejor" if lo > 0 else ("peor" if hi < 0 else "empate")
        return f"{m:+.4f} [{lo:+.4f}; {hi:+.4f}] {marca:<6}"

    print(f"{'k':>4} {'usuarios':>9} {'popular.':>9} {'user-kNN':>9} {'EASE':>8}   "
          f"{'user-kNN - popularidad (IC 95 %)':<36} EASE - popularidad (IC 95 %)")
    for f in resultados:
        linea = f"{f['k']:>4} {f['usuarios']:>9} {f['popularidad']:>9.4f}"
        if "EASE" in f:
            linea += (f" {f['user-kNN']:>9.4f} {f['EASE']:>8.4f}   "
                      f"{comparar(f['user-kNN_ic']):<36} {comparar(f['EASE_ic'])}")
        print(linea)


def graficar(resultados, ruta="resultados/ndcg_segun_historial.png"):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    ks = [f["k"] for f in resultados if "EASE" in f]
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.plot([f["k"] for f in resultados], [f["popularidad"] for f in resultados], "o-", color="#A89A88", label="popularidad")
    ax.plot(ks, [f["user-kNN"] for f in resultados if "EASE" in f], "o-", color="#D98C6F", label="user-kNN")
    ax.plot(ks, [f["EASE"] for f in resultados if "EASE" in f], "o-", color="#B5452F", linewidth=2.5, label="EASE")
    ax.set_xlabel("reseñas que el sistema conoce del usuario (k)")
    ax.set_ylabel("NDCG@10 (corte temporal)")
    ax.set_title("¿Qué modelo conviene según cuánto sabemos del usuario?")
    ax.legend(frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(ruta, dpi=150)
    print(f"Gráfico guardado en {ruta}")
