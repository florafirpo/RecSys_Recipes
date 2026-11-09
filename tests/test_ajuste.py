"""Tests de la validacion que se usa para ajustar k y lambda."""

import numpy as np
import pytest

from ajuste import medir, validacion_al_azar, validacion_temporal


def test_validacion_temporal_separa_por_fecha_y_pide_pasado():
    resenas = [
        # usuario 1: 3 reseñas antes del corte -> entra a validacion
        (1, 10, 5, "2009-01-01"), (1, 11, 5, "2009-02-01"), (1, 12, 4, "2009-03-01"),
        (1, 13, 5, "2010-05-01"),  # positiva despues del corte
        (1, 14, 2, "2010-06-01"),  # negativa: no va a validacion
        # usuario 2: solo 1 reseña antes -> no tiene pasado suficiente
        (2, 10, 5, "2009-01-01"), (2, 13, 5, "2010-05-01"),
    ]
    train, validacion = validacion_temporal(resenas, en_catalogo={10, 11, 12, 13, 14}, fecha_corte="2010-01-01")
    assert all(r[3] < "2010-01-01" for r in train)
    assert validacion == {1: {13}}


def test_validacion_al_azar_deja_al_menos_3_y_solo_esconde_positivas():
    resenas = [(1, receta, 5 if receta % 2 else 2, "2009-01-01") for receta in range(20)]
    train, validacion = validacion_al_azar(resenas, en_catalogo=set(range(20)))
    escondidas = validacion[1]
    assert len(escondidas) == 4  # 20% de 20
    assert all(receta % 2 == 1 for receta in escondidas)  # solo positivas
    assert len(train) == 16
    assert not escondidas & {r[1] for r in train}  # no quedan en train


def test_medir_cuenta_aciertos_y_no_recomienda_lo_ya_visto():
    X = np.array([[1.0, 0, 0, 0]])
    puntajes = np.array([[9.0, 1, 3, 2]])  # la receta 0 ya la vio: se saltea
    precision, mrr = medir(puntajes, X, usuarios=[7], recetas=["a", "b", "c", "d"],
                           validacion={7: {"d"}}, n=2)
    assert precision == pytest.approx(1 / 2)  # recomienda c, d -> acierta d
    assert mrr == pytest.approx(1 / 2)
