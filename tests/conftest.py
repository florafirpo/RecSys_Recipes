"""
Datos chiquitos, inventados, que comparten todos los tests.

pytest corre automaticamente las funciones marcadas con @pytest.fixture
cuando un test las pide como parametro. 'tmp_path' es una carpeta temporal
que pytest crea (y borra) para cada test: asi nunca se tocan las bases reales.
"""

import os
import sys

import pytest

# Para poder hacer "import dataset", "import recomendador", etc. desde los tests
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dataset  # noqa: E402
import recomendador  # noqa: E402
from base_datos import conectar  # noqa: E402

# id, categoria, autor, rating_value (del sitio), rating_count (del sitio)
RECETAS = [
    (10, "Postres", 1, 4.9, 900),
    (11, "Postres", 1, 4.5, 50),
    (12, "Postres", 2, 4.0, 10),   # categoria que le gusta al usuario 1, autor nuevo
    (13, "Pastas", 3, 4.8, 2000),  # la mas popular EN EL SITIO
    (14, "Pastas", 3, 4.2, 30),
    (15, "Sopas", 4, 3.9, 20),
    (16, "Sopas", 4, 4.1, 15),
    (17, "Ensaladas", 5, 4.7, 400),
]

# id_lector, id_receta, rating
INTERACCIONES = [
    # usuario 1: 6 reviews, le gustan los postres del autor 1
    (1, 10, 5), (1, 11, 5), (1, 13, 4), (1, 14, 2), (1, 15, 5), (1, 16, 4),
    # usuario 2: 4 reviews
    (2, 10, 4), (2, 13, 5), (2, 15, 5), (2, 17, 5),
    # usuario 3: cold start (2 reviews)
    (3, 10, 5), (3, 17, 4),
]


def crear_base_app(ruta, recetas=RECETAS, interacciones=INTERACCIONES):
    """Crea una recetas_app.db de juguete con el mismo esquema que la real."""
    con = conectar(str(ruta))
    dataset.crear_tablas_app(con)
    for rid, cat, autor, valor, cant in recetas:
        con.execute(
            "INSERT INTO recetas VALUES (?,?,?,?,?,?,?,?,?,?)",
            (rid, f"https://www.food.com/recipe/receta-{rid}", f"Receta {rid}", "",
             cat, valor, cant, autor, f"autor{autor}", None),
        )
    con.executemany(
        "INSERT INTO interacciones VALUES (?,?,?,'2020-01-01')", interacciones
    )
    for u in sorted({i[0] for i in interacciones}):
        con.execute("INSERT INTO usuarios VALUES (?,?,?,NULL,NULL,NULL)", (u, f"u{u}", f"u{u}"))
    con.commit()
    con.close()
    return str(ruta)


@pytest.fixture
def base_app(tmp_path):
    """Ruta a una recetas_app.db de juguete."""
    return crear_base_app(tmp_path / "recetas_app.db")


@pytest.fixture
def recomendador_de_prueba(base_app):
    """El modulo recomendador apuntando a la base de juguete.
    Al terminar el test lo vuelve a dejar como estaba."""
    anterior = recomendador.DATABASE_FILE
    recomendador.DATABASE_FILE = base_app
    yield recomendador
    recomendador.DATABASE_FILE = anterior
