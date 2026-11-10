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


def test_usuario_con_historial_usa_ease(recomendador_de_prueba):
    _, algoritmo = recomendador_de_prueba.recomendar(1, N=1, registrar_vistos=False)
    assert algoritmo.startswith("ease")


def test_ease_completa_con_top_n_si_faltan(recomendador_de_prueba):
    # En la base de juguete hay 8 recetas y el usuario 1 valoro 6: EASE no llega a 5
    rec, algoritmo = recomendador_de_prueba.recomendar(1, N=5, registrar_vistos=False)
    assert algoritmo == "ease+top_n"
    assert len(ids(rec)) == len(set(ids(rec)))  # sin repetidas


def test_ease_usa_las_valoraciones_nuevas_sin_reentrenar(recomendador_de_prueba):
    # Un usuario nuevo que valora 3 recetas pasa a recibir EASE enseguida
    for receta in (10, 13, 15):
        recomendador_de_prueba.insertar_interaccion(50, receta, 5)
    rec, algoritmo = recomendador_de_prueba.recomendar(50, N=2, registrar_vistos=False)
    assert algoritmo.startswith("ease")
    assert not {10, 13, 15} & set(ids(rec))
    # La receta 17 la reseño el usuario 2, que comparte las 3 recetas con el usuario 50
    assert ids(rec)[0] == 17


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


def test_reemplazar_en_lote_cambia_solo_esa_receta(recomendador_de_prueba):
    rec, _ = recomendador_de_prueba.recomendar_lote(99, N=3)  # usuario nuevo
    antes = ids(rec)
    elegida = antes[1]
    recomendador_de_prueba.insertar_interaccion(99, elegida, 5)
    nueva = recomendador_de_prueba.reemplazar_en_lote(99, elegida)
    despues = ids(recomendador_de_prueba.recomendar_lote(99, N=3)[0])
    assert despues[0] == antes[0] and despues[2] == antes[2]  # las otras quedan igual
    assert despues[1] == nueva["id"]
    assert nueva["id"] not in antes  # no repite ninguna del lote


def test_recetas_vistas_permite_volver_a_verlas(recomendador_de_prueba):
    rec, _ = recomendador_de_prueba.recomendar_lote(99, N=3)
    recomendador_de_prueba.insertar_interaccion(99, ids(rec)[0], 4)
    vistas = recomendador_de_prueba.recetas_vistas(99)
    assert set(ids(vistas)) == set(ids(rec))
    ratings = {r["id"]: r["mi_rating"] for r in vistas}
    assert ratings[ids(rec)[0]] == 4 and ratings[ids(rec)[1]] is None


def test_me_tienta_cuenta_para_salir_del_cold_start(recomendador_de_prueba):
    r = recomendador_de_prueba
    for receta in (10, 13, 15):
        r.marcar_senal(60, receta, "tienta")
    rec, algoritmo = r.recomendar(60, N=2, registrar_vistos=False)
    assert algoritmo.startswith("ease")
    assert not {10, 13, 15} & set(ids(rec))  # lo guardado no se recomienda de nuevo


def test_no_es_para_mi_no_se_vuelve_a_recomendar(recomendador_de_prueba):
    r = recomendador_de_prueba
    primera = ids(r.recomendador_top_n(61))[0]
    r.marcar_senal(61, primera, "no")
    assert primera not in ids(r.recomendador_top_n(61))


def test_me_tienta_funciona_como_boton_on_off(recomendador_de_prueba):
    r = recomendador_de_prueba
    assert r.marcar_senal(62, 10, "tienta") == "tienta"
    assert r.marcar_senal(62, 10, "tienta") is None
    assert r.mi_senal(62, 10) is None


def test_explicaciones_nombran_una_receta_valorada(recomendador_de_prueba):
    r = recomendador_de_prueba
    for receta in (10, 13, 15):
        r.insertar_interaccion(63, receta, 5)
    rec, _ = r.recomendar(63, N=2, registrar_vistos=False)
    por_que = r.explicaciones(63, ids(rec))
    assert por_que  # al menos una explicacion
    assert set(por_que.values()) <= {"Receta 10", "Receta 13", "Receta 15"}
    assert r.explicaciones(64, ids(rec)) == {}  # usuario sin historial: sin explicacion


def test_populares_variadas_no_repite_categoria(recomendador_de_prueba):
    elegidas = recomendador_de_prueba.populares_variadas(N=12)
    categorias = [e["category"] for e in elegidas]
    assert len(categorias) == len(set(categorias))


def test_historial_con_filtros(recomendador_de_prueba):
    r = recomendador_de_prueba
    rec, _ = r.recomendar_lote(65, N=3)
    a, b, c = ids(rec)
    r.insertar_interaccion(65, a, 5)
    r.marcar_senal(65, b, "tienta")
    assert ids(r.recetas_vistas(65, filtro="valoradas")) == [a]
    assert ids(r.recetas_vistas(65, filtro="guardadas")) == [b]
    assert set(ids(r.recetas_vistas(65, filtro="pendientes"))) == {b, c}
    r.reset_usuario(65)
    assert r.recetas_vistas(65, filtro="guardadas") == []


def test_buscar_por_ingrediente_palabra_entera(recomendador_de_prueba, tmp_path):
    r = recomendador_de_prueba
    r.sql_execute("INSERT INTO ingredientes VALUES (10, 1, 'eggs, beaten', 'egg')")
    r.sql_execute("INSERT INTO ingredientes VALUES (13, 1, 'eggplant, sliced', 'eggplant')")
    recetas, lleva = r.buscar_recetas(terminos=["egg"])
    assert ids(recetas) == [10]  # 'eggplant' no cuenta como huevo
    assert lleva[10] == "eggs, beaten"


def test_buscar_ordena_por_mejor_valoradas_y_filtra_categoria(recomendador_de_prueba):
    r = recomendador_de_prueba
    recetas, _ = r.buscar_recetas(categoria="Sopas")
    assert set(ids(recetas)) == {15, 16}
    promedios = [x["promedio"] for x in recetas]
    assert promedios == sorted(promedios, reverse=True)


def test_categorias_disponibles(recomendador_de_prueba):
    cats = dict(recomendador_de_prueba.categorias_disponibles(min_recetas=2))
    assert cats == {"Postres": 3, "Pastas": 2, "Sopas": 2}
