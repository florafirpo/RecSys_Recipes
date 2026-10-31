"""
Tests de la separacion train / test. Son los mas importantes del proyecto:
si se cuela informacion de test en train (leakage), las metricas mienten.
"""

import hashlib

import pytest

from base_datos import conectar
from dataset import separar_train_test

from conftest import crear_base_app


def pares(ruta):
    con = conectar(ruta)
    resultado = {(u, r) for u, r in con.execute("SELECT id_lector, id_receta FROM interacciones")}
    con.close()
    return resultado


@pytest.fixture
def split(base_app, tmp_path):
    """Corre la separacion sobre la base de juguete y devuelve las 3 rutas."""
    db_train, db_test = str(tmp_path / "train.db"), str(tmp_path / "test.db")
    separar_train_test(base_app, db_train, db_test,
                       fraccion_test=0.2, min_que_quedan=3, rating_positivo=4, semilla=42)
    return base_app, db_train, db_test


def test_ninguna_review_de_test_queda_en_train(split):
    _, db_train, db_test = split
    assert pares(db_train) & pares(db_test) == set()


def test_train_mas_test_es_la_base_original(split):
    db_app, db_train, db_test = split
    assert pares(db_train) | pares(db_test) == pares(db_app)


def test_test_solo_tiene_reviews_positivas(split):
    _, _, db_test = split
    con = conectar(db_test)
    ratings = [r for (r,) in con.execute("SELECT rating FROM interacciones")]
    assert ratings and min(ratings) >= 4


def test_test_solo_tiene_recetas_del_catalogo(split):
    _, db_train, db_test = split
    con = conectar(db_train)
    catalogo = {r for (r,) in con.execute("SELECT id FROM recetas WHERE title IS NOT NULL")}
    assert {r for _, r in pares(db_test)} <= catalogo


def test_cada_usuario_conserva_el_minimo_en_train(split):
    db_app, db_train, db_test = split
    usuarios_con_test = {u for u, _ in pares(db_test)}
    en_train = [u for u, _ in pares(db_train)]
    assert all(en_train.count(u) >= 3 for u in usuarios_con_test)


def test_no_se_reserva_a_usuarios_con_pocas_reviews(split):
    _, _, db_test = split
    assert 3 not in {u for u, _ in pares(db_test)}  # el usuario 3 tiene solo 2 reviews


def test_la_separacion_es_reproducible(base_app, tmp_path):
    for carpeta in ("a", "b"):
        (tmp_path / carpeta).mkdir()
        separar_train_test(base_app, str(tmp_path / carpeta / "train.db"), str(tmp_path / carpeta / "test.db"))
    assert pares(str(tmp_path / "a" / "test.db")) == pares(str(tmp_path / "b" / "test.db"))


def test_la_base_original_no_se_modifica(base_app, tmp_path):
    with open(base_app, "rb") as f:
        antes = hashlib.sha256(f.read()).hexdigest()
    separar_train_test(base_app, str(tmp_path / "train.db"), str(tmp_path / "test.db"))
    with open(base_app, "rb") as f:
        assert hashlib.sha256(f.read()).hexdigest() == antes


def test_se_reserva_la_fraccion_pedida(tmp_path):
    # un usuario con 50 reviews positivas: con 20% deja 10 en test y 40 en train
    recetas = [(100 + k, "Postres", 1, 4.5, 10) for k in range(50)]
    interacciones = [(1, 100 + k, 5) for k in range(50)]
    db_app = crear_base_app(tmp_path / "app.db", recetas, interacciones)
    db_train, db_test = str(tmp_path / "train.db"), str(tmp_path / "test.db")
    separar_train_test(db_app, db_train, db_test, fraccion_test=0.2)
    assert len(pares(db_test)) == 10
    assert len(pares(db_train)) == 40
