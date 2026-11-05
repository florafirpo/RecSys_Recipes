"""Tests del filtrado p-core y la exportacion de la matriz."""

from scipy.sparse import load_npz

from matriz import calcular_densidad, exportar_filas, filtrar_por_core, sacar_repetidas


def test_pcore_todos_cumplen_el_minimo():
    filas = [("a", 1, 5), ("a", 2, 4), ("b", 1, 5), ("b", 2, 3), ("c", 1, 5)]
    resultado = filtrar_por_core(filas, min_usuario=2, min_item=2)
    usuarios = [u for u, _, _ in resultado]
    items = [i for _, i, _ in resultado]
    assert all(usuarios.count(u) >= 2 for u in usuarios)
    assert all(items.count(i) >= 2 for i in items)
    assert "c" not in usuarios  # tenia una sola review


def test_pcore_efecto_cascada():
    # "a" y "b" cumplen el minimo al principio (2 reviews cada uno), pero al sacar
    # a "c" y "d" (1 review) las recetas 1 y 3 bajan a 1 review y salen, y eso
    # deja a "a" y "b" por debajo del minimo. Una sola vuelta no alcanzaria.
    # "e" y "f" forman un nucleo que si se sostiene.
    filas = [("a", 1, 5), ("a", 2, 5), ("b", 2, 5), ("b", 3, 5), ("c", 3, 5), ("d", 1, 5),
             ("e", 4, 5), ("e", 5, 5), ("f", 4, 5), ("f", 5, 5)]
    resultado = filtrar_por_core(filas, min_usuario=2, min_item=2)
    assert {u for u, _, _ in resultado} == {"e", "f"}


def test_pcore_puede_quedar_vacio():
    assert filtrar_por_core([("a", 1, 5)], min_usuario=2, min_item=2) == []


def test_densidad():
    filas = [("a", 1, 5), ("a", 2, 4), ("b", 1, 5)]  # 3 celdas llenas de 2x2
    assert calcular_densidad(filas) == (2, 2, 3, 0.75)


def test_densidad_vacia():
    assert calcular_densidad([]) == (0, 0, 0, 0)


def test_exportar_filas_respeta_los_indices(tmp_path):
    filas = [(100, 7, 5), (100, 9, 3), (200, 9, 4)]
    npz, csv_u, csv_i = tmp_path / "m.npz", tmp_path / "u.csv", tmp_path / "i.csv"
    exportar_filas(filas, npz, csv_u, csv_i)
    m = load_npz(npz).toarray()
    # usuarios ordenados: 100 -> fila 0, 200 -> fila 1; recetas: 7 -> col 0, 9 -> col 1
    assert m.tolist() == [[5, 3], [0, 4]]


def test_exportar_filas_no_suma_reviews_repetidas(tmp_path):
    # Antes csr_matrix sumaba las repetidas y la celda quedaba en 10
    filas = [(100, 7, 5), (100, 7, 4)]  # el mismo usuario reseño dos veces la receta 7
    npz = tmp_path / "m.npz"
    exportar_filas(filas, npz, tmp_path / "u.csv", tmp_path / "i.csv")
    assert load_npz(npz).toarray().tolist() == [[5]]  # queda la primera reseña


def test_sacar_repetidas_deja_la_primera_y_respeta_el_orden():
    filas = [(1, 7, 5), (2, 7, 3), (1, 7, 2), (1, 8, 4)]
    assert sacar_repetidas(filas) == [(1, 7, 5), (2, 7, 3), (1, 8, 4)]


def test_elegir_por_densidad_prefiere_mas_usuarios_que_cumplan():
    from matriz import elegir_por_densidad
    # nucleo denso: a, b, c leen las recetas 1, 2, 3; d solo lee la 1 y la 4 (baja la densidad)
    filas = [(u, i, 5) for u in "abc" for i in (1, 2, 3)] + [("d", 1, 5), ("d", 4, 5)]
    min_u, min_i, top, elegidas = elegir_por_densidad(filas, 0.5, grilla_usuario=(1, 2, 3), grilla_item=(1, 2, 3))
    usuarios = {u for u, _, _ in elegidas}
    assert usuarios == {"a", "b", "c", "d"}  # con minimos (1,1) entran los 4 y la densidad es 11/16 >= 0.5
    assert (min_u, min_i) == (1, 1)


def test_elegir_por_densidad_sin_combinacion_valida():
    from matriz import elegir_por_densidad
    assert elegir_por_densidad([("a", 1, 5), ("b", 2, 5)], 0.9, (1,), (1,)) is None


def test_elegir_por_densidad_usa_el_recorte_si_hace_falta():
    from matriz import elegir_por_densidad
    # sin recorte: 4 usuarios x 4 recetas con 10 reseñas -> densidad 0,625 (no llega a 0,7).
    # con las 3 recetas mas populares (1, 2, 3), d se queda sin reseñas y sale: 9/9 = 1,0
    filas = [(u, i, 5) for u in "abc" for i in (1, 2, 3)] + [("d", 4, 5)]
    resultado = elegir_por_densidad(filas, 0.7, grilla_usuario=(1,), grilla_item=(1,), grilla_top=(None, 3))
    assert resultado is not None
    min_u, min_i, top, elegidas = resultado
    assert top == 3 and {u for u, _, _ in elegidas} == {"a", "b", "c"}
