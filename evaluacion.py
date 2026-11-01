"""
Evaluacion offline de los recomendadores contra las reviews reservadas en test.

Requiere haber corrido antes la separacion train/test (python main.py split).

Para cada usuario de test se piden N recomendaciones con cada estrategia
(entrenando solo con recetas_train.db) y se comparan con las recetas que
le escondimos. Metricas (promedio entre usuarios):
  - hit rate@N : % de usuarios con al menos una receta reservada entre las N.
  - precision@N: de las N recomendadas, que fraccion eran reservadas.
  - recall@N   : de las reservadas, que fraccion aparecio entre las N.
  - MRR        : 1 / posicion del primer acierto (0 si no hubo); premia acertar arriba.
  - con N recetas: % de usuarios a los que la estrategia les llego a dar N recetas.

Para sumar un modelo nuevo, agregalo al diccionario de estrategias_a_evaluar().
Cada estrategia es una funcion que recibe id_lector y devuelve una lista de
recetas (filas con la clave "id"), ordenadas de mejor a peor.
"""

import os
import random
from collections import defaultdict

import config
import dos_etapas
import modelos
import recomendador
from base_datos import conectar


def cargar_test(db_test=config.DB_TEST):
    """Devuelve {id_lector: set(id_receta reservadas)}."""
    con = conectar(db_test)
    reservadas = defaultdict(set)
    for id_lector, id_receta in con.execute("SELECT id_lector, id_receta FROM interacciones"):
        reservadas[id_lector].add(id_receta)
    con.close()
    return reservadas


def metricas(recomendadas, reservadas, n):
    """Metricas de UN usuario, para una lista de ids recomendados."""
    aciertos = [i for i, id_receta in enumerate(recomendadas) if id_receta in reservadas]
    return {
        "hit rate@N": 1.0 if aciertos else 0.0,
        "precision@N": len(aciertos) / n,
        "recall@N": len(aciertos) / len(reservadas),
        "MRR": 1 / (aciertos[0] + 1) if aciertos else 0.0,
        "con N recetas": 1.0 if len(recomendadas) >= n else 0.0,
    }


def evaluar(estrategia, reservadas_por_usuario, n, repeticiones=1):
    """Promedia las metricas de una estrategia sobre todos los usuarios de test."""
    acumulado = defaultdict(float)
    for _ in range(repeticiones):
        for id_lector, reservadas in reservadas_por_usuario.items():
            recomendadas = [r["id"] for r in estrategia(id_lector)[:n]]
            for nombre, valor in metricas(recomendadas, reservadas, n).items():
                acumulado[nombre] += valor

    total = repeticiones * len(reservadas_por_usuario)
    return {nombre: valor / total for nombre, valor in acumulado.items()}


def comparar_contra_base(estrategia, base, reservadas_por_usuario, n,
                         metrica="precision@N", repeticiones=2000, semilla=0):
    """¿La estrategia le gana a la base de verdad, o es ruido?
    Compara usuario por usuario (comparacion pareada) y calcula un intervalo
    de confianza del 95% de la diferencia con bootstrap: se re-sortean los
    usuarios con reposicion muchas veces y se mira cuanto varia el promedio.
    Si el intervalo no incluye el 0, la diferencia es significativa.
    Devuelve (diferencia_promedio, limite_inferior, limite_superior)."""
    diferencias = []
    for id_lector, reservadas in reservadas_por_usuario.items():
        a = [r["id"] for r in estrategia(id_lector)[:n]]
        b = [r["id"] for r in base(id_lector)[:n]]
        diferencias.append(metricas(a, reservadas, n)[metrica] - metricas(b, reservadas, n)[metrica])

    azar = random.Random(semilla)
    promedios = []
    for _ in range(repeticiones):
        muestra = [azar.choice(diferencias) for _ in diferencias]
        promedios.append(sum(muestra) / len(muestra))
    promedios.sort()
    inferior = promedios[int(0.025 * repeticiones)]
    superior = promedios[int(0.975 * repeticiones) - 1]
    return sum(diferencias) / len(diferencias), inferior, superior


def estrategias_a_evaluar(n):
    """Las estrategias que se comparan. Aca se suman los modelos nuevos.
    Los modelos colaborativos se entrenan con la base que este usando el
    recomendador en ese momento (en la evaluacion, train)."""
    X, usuarios, recetas = modelos.cargar_matriz(recomendador.DATABASE_FILE)
    user_knn = modelos.puntajes_user_knn(X, config.K_VECINOS)
    ease = modelos.puntajes_ease(X, config.LAMBDA_EASE)
    return {
        "azar": recomendador.recomendador_azar,
        "top_n": recomendador.recomendador_top_n,
        "perfil": recomendador.recomendador_perfil,
        "recomendar (perfil+top_n)": lambda id_lector: recomendador.recomendar(
            id_lector, n, registrar_vistos=False
        )[0],
        f"user-kNN (k={config.K_VECINOS})": modelos.crear_estrategia(user_knn, X, usuarios, recetas),
        f"EASE (lambda={config.LAMBDA_EASE})": modelos.crear_estrategia(ease, X, usuarios, recetas),
        "populares recientes": dos_etapas.crear_populares_recientes(recomendador.DATABASE_FILE, n),
        "dos etapas (retrieval + ranking)": dos_etapas.crear_dos_etapas(recomendador.DATABASE_FILE, n),
    }


def imprimir_tabla(resultados):
    columnas = list(next(iter(resultados.values())).keys())
    ancho = max(len(nombre) for nombre in resultados) + 2
    print("estrategia".ljust(ancho) + "".join(c.rjust(15) for c in columnas))
    for nombre, valores in resultados.items():
        print(nombre.ljust(ancho) + "".join(f"{valores[c]:15.3f}" for c in columnas))


def evaluar_todo(db_train=config.DB_TRAIN, db_test=config.DB_TEST,
                 n=config.N_RECOMENDACIONES, repeticiones_azar=config.REPETICIONES_AZAR):
    """Evalua todas las estrategias y muestra la tabla. Devuelve los resultados."""
    if not (os.path.exists(db_train) and os.path.exists(db_test)):
        print("Faltan las bases de train/test: corré primero  python main.py split")
        return None

    base_anterior = recomendador.DATABASE_FILE
    recomendador.DATABASE_FILE = db_train  # el recomendador solo ve train
    try:
        reservadas_por_usuario = cargar_test(db_test)
        print(f"Evaluando {len(reservadas_por_usuario)} usuarios, N = {n}\n")

        estrategias = estrategias_a_evaluar(n)
        resultados = {}
        for nombre, estrategia in estrategias.items():
            repeticiones = repeticiones_azar if nombre == "azar" else 1
            resultados[nombre] = evaluar(estrategia, reservadas_por_usuario, n, repeticiones)

        imprimir_tabla(resultados)

        print("\nDiferencia de precision@N contra top_n (intervalo de confianza 95%, bootstrap pareado):")
        for nombre, estrategia in estrategias.items():
            if nombre in ("azar", "top_n"):
                continue
            dif, inf, sup = comparar_contra_base(estrategia, estrategias["top_n"], reservadas_por_usuario, n)
            veredicto = "significativa" if inf > 0 or sup < 0 else "no significativa"
            print(f"  {nombre:28s} {dif:+.3f}  [{inf:+.3f}, {sup:+.3f}]  {veredicto}")
    finally:
        recomendador.DATABASE_FILE = base_anterior

    return resultados
