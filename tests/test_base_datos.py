"""Tests de las funciones de ayuda de base_datos.py."""

import sqlite3

from base_datos import consulta_por_lotes, id_food_desde_url


def test_id_food_desde_url_toma_el_numero_final():
    assert id_food_desde_url("https://www.food.com/recipe/greek-salad-290186") == 290186


def test_id_food_desde_url_tolera_barra_final():
    assert id_food_desde_url("https://www.food.com/recipe/greek-salad-290186/") == 290186


def test_id_food_desde_url_sin_numero_devuelve_none():
    assert id_food_desde_url("https://www.food.com/recipe/greek-salad") is None
    assert id_food_desde_url("") is None
    assert id_food_desde_url(None) is None


def test_consulta_por_lotes_junta_todos_los_lotes():
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE t (x INTEGER)")
    con.executemany("INSERT INTO t VALUES (?)", [(i,) for i in range(1, 21)])
    filas = consulta_por_lotes(con, "SELECT x FROM t WHERE x IN ({ph})", range(1, 21), tam_lote=7)
    assert sorted(f[0] for f in filas) == list(range(1, 21))
