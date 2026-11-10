"""Tests de la copia de pasos de preparacion y cantidades desde el scraping."""

import json
import sqlite3

import dataset
from conftest import crear_base_app


def test_pasos_desde_json_acepta_varias_formas():
    assert dataset.pasos_desde_json(json.dumps(["Preheat oven.", "Mix &amp; bake."])) == ["Preheat oven.", "Mix & bake."]
    assert dataset.pasos_desde_json(json.dumps([{"text": "Paso <b>uno</b>"}, {"displayText": "Paso dos"}])) == ["Paso uno", "Paso dos"]
    assert dataset.pasos_desde_json(json.dumps([{"steps": [{"text": "Anidado"}]}])) == ["Anidado"]
    assert dataset.pasos_desde_json(json.dumps("350&deg;F")) == ["350°F"]
    assert dataset.pasos_desde_json(None) == [] and dataset.pasos_desde_json("no es json") == []


def crear_scraping(ruta):
    con = sqlite3.connect(ruta)
    con.execute("CREATE TABLE recetas (id INTEGER PRIMARY KEY, url TEXT, scraped_ok INTEGER, directions_json TEXT)")
    con.execute("CREATE TABLE ingredientes (recipe_id INTEGER, orden INTEGER, quantity TEXT, texto_completo TEXT)")
    # id interno 1 = receta real 10 (el numero final de la URL)
    con.execute("INSERT INTO recetas VALUES (1, 'https://www.food.com/recipe/torta-10', 1, ?)",
                [json.dumps([{"text": "Precalentar el horno."}, {"text": "Hornear 30 minutos."}])])
    con.executemany("INSERT INTO ingredientes VALUES (1, ?, ?, ?)", [(1, "2", "cups flour"), (2, "", "salt")])
    con.commit()
    con.close()


def test_agregar_preparacion_completa_una_base_existente(tmp_path):
    origen = tmp_path / "food_scraping.db"
    crear_scraping(origen)
    app = crear_base_app(tmp_path / "recetas_app.db")
    con = sqlite3.connect(app)
    con.executemany("INSERT INTO ingredientes VALUES (10, ?, ?, NULL)", [(1, "cups flour"), (2, "salt")])
    con.commit()
    con.close()

    dataset.agregar_preparacion(db_origen=str(origen), db_app=app)

    con = sqlite3.connect(app)
    assert con.execute("SELECT texto FROM preparacion WHERE recipe_id = 10 ORDER BY paso").fetchall() == [
        ("Precalentar el horno.",), ("Hornear 30 minutos.",)]
    assert con.execute("SELECT cantidad FROM ingredientes WHERE recipe_id = 10 ORDER BY orden").fetchall() == [
        ("2",), (None,)]
    con.close()


def test_la_pagina_muestra_pasos_y_cantidades(tmp_path, recomendador_de_prueba):
    origen = tmp_path / "food_scraping.db"
    crear_scraping(origen)
    r = recomendador_de_prueba
    assert r.obtener_preparacion(10) == []  # base sin pasos: lista vacia, sin error
    r.sql_execute("INSERT INTO ingredientes VALUES (10, 1, 'cups flour', NULL)")
    dataset.agregar_preparacion(db_origen=str(origen), db_app=r.DATABASE_FILE)
    assert r.obtener_preparacion(10) == ["Precalentar el horno.", "Hornear 30 minutos."]
    assert r.obtener_ingredientes(10) == ["2 cups flour"]
