"""
Matriz usuario x receta: filtrado p-core para subir la densidad y exportacion.

POR QUE HACE FALTA:
  Con ~298.000 recetas, ~158.000 usuarios y ~573.000 comentarios, la matriz
  completa tiene una densidad de ~0.0012% (MovieLens 100k, el dataset
  clasico de la materia, tiene 6.30%). Para que el filtrado colaborativo
  tenga sentido nos quedamos con un subconjunto donde usuarios y recetas
  tengan una actividad minima garantizada.

COMO FUNCIONA EL FILTRADO (p-core):
  1. Fijamos un minimo de interacciones por usuario y por receta.
  2. Sacamos a los usuarios/recetas que no llegan a ese minimo.
  3. Como sacar unos puede hacer que otros ya no cumplan, repetimos hasta
     que se estabiliza (nadie queda por debajo del minimo).
  4. Cuanto mas alto el minimo, menos sobreviven pero mas sube la densidad.

Las interacciones se manejan como una lista de tuplas (usuario, receta, rating).
"""

import csv

from scipy.sparse import csr_matrix, save_npz

from base_datos import conectar


def cargar_interacciones(ruta_db):
    """Trae (member_id, recipe_id, rating) de todos los comentarios con rating
    valido (se excluyen las reseñas sin estrellas, rating 0). Son ~570.000
    filas de 3 numeros: entran comodas en memoria."""
    con = conectar(ruta_db)
    filas = con.execute("""
        SELECT member_id, recipe_id, rating
        FROM comentarios
        WHERE member_id IS NOT NULL AND recipe_id IS NOT NULL
          AND rating IS NOT NULL AND rating > 0
    """).fetchall()
    con.close()
    return sacar_repetidas(filas)


def sacar_repetidas(filas):
    """Si un usuario reseño dos veces la misma receta, deja solo la primera
    reseña (la misma regla que usa dataset.py con INSERT OR IGNORE).
    Si no, el p-core las contaria dos veces y csr_matrix sumaria los
    ratings (una celda podria quedar en 10)."""
    vistas = set()
    resultado = []
    for u, i, r in filas:
        if (u, i) not in vistas:
            vistas.add((u, i))
            resultado.append((u, i, r))
    return resultado


def filtrar_por_core(interacciones, min_usuario, min_item):
    """Filtrado iterativo (p-core). Devuelve la lista filtrada donde todo
    usuario y toda receta que queda tiene al menos el minimo pedido."""
    filas = list(interacciones)

    while True:
        conteo_usuarios = {}
        conteo_items = {}
        for u, i, _ in filas:
            conteo_usuarios[u] = conteo_usuarios.get(u, 0) + 1
            conteo_items[i] = conteo_items.get(i, 0) + 1

        antes = len(filas)
        filas = [
            (u, i, r) for (u, i, r) in filas
            if conteo_usuarios[u] >= min_usuario and conteo_items[i] >= min_item
        ]

        # Si en esta vuelta no sacamos nada, se estabilizo
        if len(filas) == antes or not filas:
            break

    return filas


def calcular_densidad(filas):
    """Devuelve (usuarios, recetas, interacciones, densidad)."""
    n_usuarios = len({u for u, _, _ in filas})
    n_items = len({i for _, i, _ in filas})
    n_interacciones = len(filas)
    densidad = (n_interacciones / (n_usuarios * n_items)) if (n_usuarios and n_items) else 0
    return n_usuarios, n_items, n_interacciones, densidad


def recortar_top_items(filas, n_top, min_u, min_i):
    """Se queda con las n_top recetas con mas interacciones y vuelve a aplicar
    el filtro de minimos (algunos usuarios pueden quedar por debajo y salir)."""
    conteo = {}
    for _, i, _ in filas:
        conteo[i] = conteo.get(i, 0) + 1
    top = set(sorted(conteo, key=conteo.get, reverse=True)[:n_top])
    return filtrar_por_core([f for f in filas if f[1] in top], min_u, min_i)


# ---------------------------------------------------------------------------
# Tablas para elegir los minimos
# ---------------------------------------------------------------------------

def explorar(interacciones, combinaciones):
    """Muestra usuarios, recetas, interacciones y densidad para cada
    combinacion (min_usuario, min_item). No escribe ningun archivo."""
    print(f"\nTotal de interacciones cargadas (antes de filtrar): {len(interacciones)}")
    print(f"{'min_usuario':>11} {'min_item':>9} {'usuarios':>9} {'recetas':>9} {'interacciones':>14} {'densidad':>10}")
    print("-" * 70)
    for min_u, min_i in combinaciones:
        n_u, n_i, n_int, dens = calcular_densidad(filtrar_por_core(interacciones, min_u, min_i))
        print(f"{min_u:>11} {min_i:>9} {n_u:>9} {n_i:>9} {n_int:>14} {dens*100:>9.2f}%")

    print("\nElegí la fila más cercana al ~5% sin perder demasiados usuarios/recetas.")
    print("Conviene dejar un margen respecto del borde: un minimo apenas mas bajo que el")
    print("ultimo que sobrevive, porque cerca del borde un cambio chico hace colapsar todo.")


def tabla_top(interacciones, min_u, min_i, tamanios):
    """Muestra como quedaria la matriz recortando a las N recetas mas populares."""
    base = filtrar_por_core(interacciones, min_u, min_i)
    n_u, n_i, n_int, dens = calcular_densidad(base)
    print(f"\nBase con p-core ({min_u}, {min_i}): {n_u} usuarios, {n_i} recetas, {n_int} interacciones, densidad {dens*100:.2f}%\n")
    print(f"{'recetas_top':>11} {'usuarios':>9} {'recetas':>9} {'interacciones':>14} {'densidad':>10} {'inter/usuario':>14} {'inter/receta':>13}")
    print("-" * 88)
    for n_top in tamanios:
        if n_top >= n_i:
            continue
        u, i, k, d = calcular_densidad(recortar_top_items(base, n_top, min_u, min_i))
        print(f"{n_top:>11} {u:>9} {i:>9} {k:>14} {d*100:>9.2f}% {(k/u if u else 0):>14.1f} {(k/i if i else 0):>13.1f}")


# ---------------------------------------------------------------------------
# Exportacion
# ---------------------------------------------------------------------------

def exportar_filas(filas, ruta_npz, ruta_csv_usuarios, ruta_csv_items):
    """Guarda la matriz dispersa (.npz de scipy, filas=usuarios, columnas=recetas,
    valores=rating) y dos CSV que dicen a que usuario/receta corresponde cada
    fila/columna."""
    filas = sacar_repetidas(filas)  # por las dudas, si las filas no vienen de cargar_interacciones
    n_u, n_i, n_int, dens = calcular_densidad(filas)
    print(f"\nMatriz final: {n_u} usuarios x {n_i} recetas, {n_int} interacciones, densidad {dens*100:.2f}%")

    usuarios_ordenados = sorted({u for u, _, _ in filas})
    items_ordenados = sorted({i for _, i, _ in filas})
    indice_usuario = {u: idx for idx, u in enumerate(usuarios_ordenados)}
    indice_item = {i: idx for idx, i in enumerate(items_ordenados)}

    filas_matriz = [indice_usuario[u] for u, _, _ in filas]
    columnas_matriz = [indice_item[i] for _, i, _ in filas]
    valores = [r if r is not None else 0 for _, _, r in filas]

    matriz = csr_matrix(
        (valores, (filas_matriz, columnas_matriz)),
        shape=(len(usuarios_ordenados), len(items_ordenados))
    )
    save_npz(ruta_npz, matriz)
    print(f"Matriz dispersa guardada en '{ruta_npz}' (formato scipy CSR).")

    with open(ruta_csv_usuarios, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["fila_matriz", "member_id"])
        for idx, u in enumerate(usuarios_ordenados):
            writer.writerow([idx, u])
    print(f"Índice de usuarios guardado en '{ruta_csv_usuarios}'.")

    with open(ruta_csv_items, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["columna_matriz", "recipe_id"])
        for idx, i in enumerate(items_ordenados):
            writer.writerow([idx, i])
    print(f"Índice de recetas guardado en '{ruta_csv_items}'.")


# ---------------------------------------------------------------------------
# Eleccion automatica de los minimos
# ---------------------------------------------------------------------------

def elegir_por_densidad(interacciones, densidad_minima, grilla_usuario, grilla_item):
    """Prueba todas las combinaciones (min_usuario, min_item) de las grillas y
    devuelve la que deja MAS USUARIOS con una densidad de al menos
    densidad_minima (si empatan en usuarios, la de mas interacciones).
    Imprime la tabla completa. Devuelve (min_usuario, min_item, filas) o None."""
    print(f"\nBuscando la combinacion con mas usuarios y densidad >= {densidad_minima:.1%}")
    print(f"{'min_usuario':>11} {'min_item':>9} {'usuarios':>9} {'recetas':>9} {'interacciones':>14} {'densidad':>10}")
    print("-" * 70)
    mejor = None
    for min_u in grilla_usuario:
        for min_i in grilla_item:
            filas = filtrar_por_core(interacciones, min_u, min_i)
            n_u, n_i, n_int, dens = calcular_densidad(filas)
            cumple = dens >= densidad_minima and n_u > 0
            marca = "  <- cumple" if cumple else ""
            print(f"{min_u:>11} {min_i:>9} {n_u:>9} {n_i:>9} {n_int:>14} {dens*100:>9.2f}%{marca}")
            if cumple and (mejor is None or (n_u, n_int) > (mejor[3], mejor[4])):
                mejor = (min_u, min_i, filas, n_u, n_int)
    if mejor is None:
        print("\nNinguna combinacion llega a esa densidad.")
        return None
    print(f"\nElegida: min_usuario={mejor[0]}, min_item={mejor[1]} ({mejor[3]} usuarios, {mejor[4]} interacciones)")
    return mejor[0], mejor[1], mejor[2]
