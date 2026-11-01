"""Tests del recomendador en dos etapas (recetas)."""

import pandas as pd

import dos_etapas
from base_datos import conectar


def fechar(ruta):
    con = conectar(ruta)
    con.execute("UPDATE interacciones SET fecha = '2008-06-01T10:00:00Z'")
    con.execute("UPDATE interacciones SET fecha = '2010-06-01T10:00:00Z' WHERE id_receta IN (13, 17)")
    con.commit()
    con.close()


def test_fechas_se_leen_como_datetime(base_app):
    fechar(base_app)
    interacciones, recetas = dos_etapas.cargar_tablas(base_app)
    assert interacciones["fecha_dt"].notna().all()
    assert set(recetas["id"]) == {10, 11, 12, 13, 14, 15, 16, 17}


def test_candidatos_no_incluyen_recetas_resenadas(base_app):
    fechar(base_app)
    interacciones, recetas = dos_etapas.cargar_tablas(base_app)
    fuentes = dos_etapas.preparar_fuentes(interacciones, recetas)
    for usuario, resenadas in fuentes["resenadas"].items():
        tabla = dos_etapas.candidatos_con_variables(fuentes, usuario)
        assert not set(tabla["id"]) & resenadas
        assert list(tabla.columns) == ["id"] + dos_etapas.VARIABLES


def test_las_fuentes_del_ranker_solo_ven_el_pasado(base_app, monkeypatch):
    fechar(base_app)
    interacciones, recetas = dos_etapas.cargar_tablas(base_app)
    capturado = {}
    original = dos_etapas.preparar_fuentes

    def espia(inter, rec):
        capturado["max"] = inter["fecha_dt"].max()
        return original(inter, rec)

    monkeypatch.setattr(dos_etapas, "preparar_fuentes", espia)
    try:
        dos_etapas.entrenar_ranker(interacciones, recetas, "2010-01-01", min_resenas=1)
    except ValueError:
        pass  # con datos de juguete puede faltar una de las dos clases; lo que importa es el corte
    assert capturado["max"] < pd.Timestamp("2010-01-01")
