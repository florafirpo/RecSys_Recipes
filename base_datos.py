"""
Funciones chicas de ayuda para trabajar con las bases SQLite y los CSV.

Antes estaban copiadas en varios scripts (id_food_desde_url aparecia en 7).
"""

import csv
import sqlite3

TAM_LOTE = 500  # cuantos '?' ponemos por consulta (SQLite limita la cantidad)


def conectar(ruta, solo_lectura=False):
    """Abre una base SQLite. Con solo_lectura=True no se puede modificar
    (sirve para los analisis, asi es imposible romper la base por error)."""
    if solo_lectura:
        return sqlite3.connect(f"file:{ruta}?mode=ro", uri=True)
    return sqlite3.connect(ruta)


def id_food_desde_url(url):
    """El id real de food.com es el numero que va al final de la URL
    (ej. .../recipe/greek-salad-290186 -> 290186).
    Devuelve None si la URL no termina en un numero."""
    if not url:
        return None
    ultimo = url.rstrip("/").rsplit("-", 1)[-1]
    return int(ultimo) if ultimo.isdigit() else None


def consulta_por_lotes(con, sql, valores, tam_lote=TAM_LOTE):
    """Corre 'sql' (con un {ph} donde van los '?') en lotes y junta las filas.
    Hace falta porque SQLite no acepta un IN (...) con miles de valores."""
    filas = []
    valores = list(valores)
    for i in range(0, len(valores), tam_lote):
        lote = valores[i:i + tam_lote]
        ph = ",".join("?" * len(lote))
        filas.extend(con.execute(sql.format(ph=ph), lote).fetchall())
    return filas


def leer_ids_del_csv(ruta, columna):
    """Lee una columna de ids (enteros) de un CSV con encabezado."""
    ids = []
    with open(ruta, newline="", encoding="utf-8") as f:
        for fila in csv.DictReader(f):
            ids.append(int(fila[columna]))
    return ids
