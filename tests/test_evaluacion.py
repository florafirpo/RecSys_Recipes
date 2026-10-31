"""Tests de las metricas de evaluacion (cuentas hechas a mano)."""

import pytest

from evaluacion import evaluar, metricas


def test_metricas_con_un_acierto_en_la_posicion_2():
    m = metricas(recomendadas=[1, 2, 3, 4], reservadas={2, 9}, n=4)
    assert m["hit rate@N"] == 1.0
    assert m["precision@N"] == pytest.approx(1 / 4)
    assert m["recall@N"] == pytest.approx(1 / 2)
    assert m["MRR"] == pytest.approx(1 / 2)
    assert m["con N recetas"] == 1.0


def test_metricas_sin_aciertos():
    m = metricas(recomendadas=[1, 2], reservadas={9}, n=4)
    assert m["hit rate@N"] == m["precision@N"] == m["recall@N"] == m["MRR"] == 0.0
    assert m["con N recetas"] == 0.0  # dio 2 de las 4 pedidas


def test_evaluar_promedia_entre_usuarios():
    def estrategia(id_lector):  # siempre recomienda las recetas 1 y 2
        return [{"id": 1}, {"id": 2}]

    reservadas = {"u1": {1}, "u2": {9}}  # u1 acierta, u2 no
    resultado = evaluar(estrategia, reservadas, n=2)
    assert resultado["hit rate@N"] == pytest.approx(0.5)


def test_comparar_contra_base_detecta_una_mejora_clara():
    from evaluacion import comparar_contra_base

    reservadas = {u: {1} for u in range(50)}
    buena = lambda u: [{"id": 1}, {"id": 2}]   # siempre acierta
    mala = lambda u: [{"id": 3}, {"id": 4}]    # nunca acierta
    dif, inf, sup = comparar_contra_base(buena, mala, reservadas, n=2)
    assert dif == pytest.approx(0.5)
    assert inf > 0  # significativa
