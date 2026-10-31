"""
Tests del recomendador sobre la base de juguete (ver conftest.py).

Los dos ultimos tests reproducen bugs que ya se corrigieron: quedan para
que no vuelvan a aparecer (tests de regresion).
"""

import config


def ids(recetas):
    return [r["id"] for r in recetas]


def test_no_recomienda_recetas_ya_valoradas(recomendador_de_prueba):
    rec, _ = recomendador_de_prueba.recomendar(1, N=10, registrar_vistos=False)
    valoradas = set(recomendador_de_prueba.items_valorados(1))
    assert not set(ids(rec)) & valoradas


def test_no_recomienda_recetas_ya_vistas(recomendador_de_prueba):
    recomendador_de_prueba.insertar_vistos(2, [11, 12])
    rec, _ = recomendador_de_prueba.recomendar(2, N=10, registrar_vistos=False)
    assert not {11, 12} & set(ids(rec))


def test_registrar_vistos_false_no_modifica_la_base(recomendador_de_prueba):
    recomendador_de_prueba.recomendar(1, N=3, registrar_vistos=False)
    assert recomendador_de_prueba.items_vistos(1) == []


def test_registrar_vistos_true_guarda_lo_recomendado(recomendador_de_prueba):
    rec, _ = recomendador_de_prueba.recomendar(1, N=2)
    assert sorted(recomendador_de_prueba.items_vistos(1)) == sorted(ids(rec))


def test_cold_start_usa_popularidad(recomendador_de_prueba):
    assert len(recomendador_de_prueba.items_valorados(3)) <= config.MAX_VALORADAS_COLD_START
    _, algoritmo = recomendador_de_prueba.recomendar(3, N=3, registrar_vistos=False)
    assert algoritmo == "top_n"


def test_usuario_con_historial_usa_perfil(recomendador_de_prueba):
    _, algoritmo = recomendador_de_prueba.recomendar(1, N=1, registrar_vistos=False)
    assert algoritmo.startswith("perfil")


def test_perfil_incluye_categoria_favorita_de_autor_nuevo(recomendador_de_prueba):
    # Antes fallaba: perfil usaba JOIN con el perfil de autor y descartaba
    # recetas de autores nuevos aunque fueran de una categoria favorita.
    # Al usuario 1 le gustan los Postres; la receta 12 es un postre del autor 2 (nuevo para el)
    assert 12 in ids(recomendador_de_prueba.recomendador_perfil(1))


def test_top_n_solo_usa_interacciones_de_la_base(recomendador_de_prueba):
    # Antes era leakage: top_n usaba rating_value/rating_count de food.com.
    # En la base de juguete la receta 10 es la que suma mas puntos (5+4+5), pero
    # la 13 es la mas popular en el sitio. Con popularidad de la base, gana la 10.
    rec = recomendador_de_prueba.recomendador_top_n(99)  # usuario sin historial
    assert ids(rec)[0] == 10


def test_top_populares_coincide_con_top_n_para_usuario_nuevo(recomendador_de_prueba):
    assert ids(recomendador_de_prueba.top_populares(3)) == ids(recomendador_de_prueba.recomendador_top_n(99))[:3]
