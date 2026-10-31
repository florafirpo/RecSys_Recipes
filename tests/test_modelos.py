"""Tests de los modelos colaborativos (modelos.py), con matrices chiquitas."""

import numpy as np

import modelos


def test_cargar_matriz_es_binaria_y_tiene_la_forma_correcta(base_app):
    X, usuarios, recetas = modelos.cargar_matriz(base_app)
    assert X.shape == (len(usuarios), len(recetas))
    assert set(np.unique(X)) <= {0.0, 1.0}
    # el usuario 1 tiene 6 reseñas en la base de juguete
    assert X[usuarios.index(1)].sum() == 6


def test_user_knn_recomienda_lo_que_reseño_el_vecino():
    # usuarios 0 y 1 coinciden en las recetas 0 y 1; el 1 ademas reseño la 2
    X = np.array([[1, 1, 0, 0],
                  [1, 1, 1, 0],
                  [0, 0, 0, 1]], dtype=float)
    puntajes = modelos.puntajes_user_knn(X, k=1)
    assert puntajes[0, 2] > puntajes[0, 3]


def test_ease_una_receta_no_se_recomienda_a_si_misma():
    # el ultimo usuario reseño solo la receta 0: su puntaje para la receta 0
    # sale solo del peso B[0, 0], que EASE obliga a ser 0
    X = np.array([[1, 1, 0], [1, 0, 1], [0, 1, 1], [1, 0, 0]], dtype=float)
    puntajes = modelos.puntajes_ease(X, lambda_=1)
    assert puntajes[3, 0] == 0
    assert puntajes[3, 1] > 0 and puntajes[3, 2] > 0  # las otras si reciben puntaje


def test_estrategia_no_repite_recetas_reseñadas():
    X = np.array([[1, 0, 1], [0, 1, 0]], dtype=float)
    puntajes = np.array([[9.0, 1.0, 8.0], [1.0, 9.0, 2.0]])
    estrategia = modelos.crear_estrategia(puntajes, X, usuarios=[10, 20], recetas=[100, 200, 300])
    assert [r["id"] for r in estrategia(10)] == [200]
    assert [r["id"] for r in estrategia(20)] == [300, 100]


def test_estrategia_usuario_desconocido_recibe_popularidad(recomendador_de_prueba):
    X = np.array([[1, 0]], dtype=float)
    estrategia = modelos.crear_estrategia(np.zeros((1, 2)), X, usuarios=[1], recetas=[10, 11])
    recomendadas = [r["id"] for r in estrategia(999)]
    assert recomendadas == [r["id"] for r in recomendador_de_prueba.recomendador_top_n(999)]
