"""
EDA (analisis exploratorio) de la base simplificada recetas_app.db.

hacer_eda():
  Imprime un resumen de la matriz usuario x receta (tamaño, densidad,
  reseñas por usuario y por receta, ratings, fechas, categorias y autores),
  guarda los graficos (PNG) y un resumen.txt en la carpeta de salida.
  Las secciones que cruzan 'interacciones' con 'recetas' solo se hacen si
  los ids de 'recetas' estan alineados con las URLs; si no, se saltean,
  porque mostrarian recetas equivocadas.

comparar_con_sitio():
  ¿Las reseñas que bajamos puntuan mas alto que el promedio real del sitio?
  (el feed de food.com viene ordenado por "mas likes primero").

Solo LEEN la base, no modifican nada.
"""

import os
import statistics as st
from collections import Counter

import matplotlib
matplotlib.use("Agg")  # guardar a archivo, sin abrir ventanas
import matplotlib.pyplot as plt
import numpy as np

import config
from base_datos import conectar, id_food_desde_url

# ---- Estilo (una sola paleta para todos los graficos) ----
SUPERFICIE = "#fcfcfb"
TEXTO = "#0b0b0b"
TEXTO_SUAVE = "#52514e"
GRILLA = "#e6e5e1"
AZUL = "#2a78d6"      # la serie principal
NARANJA = "#eb6834"   # el dato que queremos destacar / segunda marca

plt.rcParams.update({
    "figure.facecolor": SUPERFICIE,
    "axes.facecolor": SUPERFICIE,
    "savefig.facecolor": SUPERFICIE,
    "text.color": TEXTO,
    "axes.labelcolor": TEXTO_SUAVE,
    "xtick.color": TEXTO_SUAVE,
    "ytick.color": TEXTO_SUAVE,
    "axes.edgecolor": GRILLA,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "axes.axisbelow": True,
    "grid.color": GRILLA,
    "grid.linewidth": 0.8,
    "font.size": 11,
})


# ---------------------------------------------------------------------------
# Ayudas
# ---------------------------------------------------------------------------

def preparar_ejes(titulo, subtitulo=None, ancho=8.5, alto=4.8, grilla_x=False):
    fig, ax = plt.subplots(figsize=(ancho, alto))
    ax.grid(axis="x", visible=grilla_x)
    fig.text(0.06, 0.95, titulo, fontsize=14, fontweight="bold", ha="left", va="top")
    if subtitulo:
        fig.text(0.06, 0.885, subtitulo, fontsize=10.5, color=TEXTO_SUAVE, ha="left", va="top")
    fig.subplots_adjust(top=0.80, left=0.09, right=0.96, bottom=0.14)
    return fig, ax


def guardar(fig, carpeta, nombre):
    ruta = os.path.join(carpeta, nombre)
    fig.savefig(ruta, dpi=160)
    plt.close(fig)
    print(f"  grafico guardado: {ruta}")


def pct(x, total):
    return f"{100 * x / total:.1f}%"


def decir(lineas, texto=""):
    """Imprime el texto y lo anota para el resumen.txt."""
    print(texto)
    lineas.append(texto)


# ---------------------------------------------------------------------------
# Secciones del EDA (cada una recibe las interacciones y la lista 'lineas')
# ---------------------------------------------------------------------------

def seccion_matriz(inter, lineas):
    """1. Tamaño y densidad de la matriz."""
    n_int = len(inter)
    n_u = len({r[0] for r in inter})
    n_i = len({r[1] for r in inter})
    densidad = n_int / (n_u * n_i)
    decir(lineas, "=== 1. Matriz usuario x receta ===")
    decir(lineas, f"Usuarios con interacciones : {n_u}")
    decir(lineas, f"Recetas con interacciones  : {n_i}")
    decir(lineas, f"Interacciones              : {n_int}")
    decir(lineas, f"Densidad                   : {100 * densidad:.2f}%  (celdas llenas / usuarios x recetas)")


def seccion_usuarios(inter, lineas, carpeta):
    """2. Reseñas por usuario y concentracion de la actividad."""
    por_usuario = Counter(r[0] for r in inter)
    n_u = len(por_usuario)
    v = np.array(sorted(por_usuario.values()))
    decir(lineas, "\n=== 2. Resenas por usuario ===")
    decir(lineas, f"Promedio : {v.mean():.1f}")
    decir(lineas, f"Mediana  : {np.median(v):.0f}")
    decir(lineas, f"Minimo / maximo : {v.min()} / {v.max()}")
    decir(lineas, "Percentiles 10/25/75/90 : " + " / ".join(str(int(np.percentile(v, p))) for p in (10, 25, 75, 90)))
    decir(lineas, f"Usuarios con menos de 3 resenas : {(v < 3).sum()}")

    fig, ax = preparar_ejes(
        "La mayoria de los usuarios tiene pocas resenas; unos pocos tienen muchisimas",
        f"Resenas por usuario ({n_u} usuarios). El promedio queda por encima de la mediana porque la cola es larga.")
    ax.hist(v, bins=np.arange(0, v.max() + 10, 10), color=AZUL, edgecolor=SUPERFICIE, linewidth=1.5)
    ymax = ax.get_ylim()[1]
    ax.set_ylim(0, ymax * 1.25)
    ax.axvline(np.median(v), color=TEXTO, linewidth=1.2)
    ax.axvline(v.mean(), color=NARANJA, linewidth=1.6)
    ax.text(np.median(v) - 2, ymax * 1.2, f"mediana {np.median(v):.0f}", ha="right", va="top", fontsize=10, color=TEXTO)
    ax.text(v.mean() + 2, ymax * 1.2, f"promedio {v.mean():.1f}", ha="left", va="top", fontsize=10, color=TEXTO)
    ax.set_xlabel("Resenas por usuario")
    ax.set_ylabel("Cantidad de usuarios")
    guardar(fig, carpeta, "1_resenas_por_usuario.png")

    # Concentracion: que parte de las reseñas pone el 10% / 25% de usuarios mas activos
    orden = v[::-1]
    acum = np.cumsum(orden) / orden.sum()
    frac_u = np.arange(1, len(orden) + 1) / len(orden)
    top10 = acum[int(np.ceil(0.10 * len(orden))) - 1]
    top25 = acum[int(np.ceil(0.25 * len(orden))) - 1]
    decir(lineas, f"El 10% de usuarios mas activos concentra el {100 * top10:.0f}% de las resenas; el 25%, el {100 * top25:.0f}%.")

    fig, ax = preparar_ejes(
        f"El 10% de usuarios mas activos pone el {100 * top10:.0f}% de las resenas",
        "Porcentaje acumulado de resenas, ordenando a los usuarios de mas a menos activo.")
    ax.plot([0, 1], [0, 1], color=GRILLA, linewidth=1.5)
    ax.text(0.62, 0.55, "si todos tuvieran\nlas mismas resenas", color=TEXTO_SUAVE, fontsize=10, rotation=0)
    ax.plot(np.r_[0, frac_u], np.r_[0, acum], color=AZUL, linewidth=2.2)
    for f, val in ((0.10, top10), (0.25, top25)):
        ax.plot([f], [val], marker="o", markersize=8, color=AZUL, markeredgecolor=SUPERFICIE, markeredgewidth=2)
        ax.text(f + 0.02, val - 0.06, f"{int(f * 100)}% de usuarios -> {100 * val:.0f}% de resenas", fontsize=10, color=TEXTO)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1.02)
    ax.xaxis.set_major_formatter(lambda x, _: f"{int(x * 100)}%")
    ax.yaxis.set_major_formatter(lambda y, _: f"{int(y * 100)}%")
    ax.set_xlabel("Usuarios (de mas a menos activo)")
    ax.set_ylabel("Resenas acumuladas")
    guardar(fig, carpeta, "2_concentracion_usuarios.png")


def seccion_recetas(inter, lineas, carpeta):
    """3. Reseñas por receta."""
    por_receta = Counter(r[1] for r in inter)
    n_i = len(por_receta)
    r = np.array(sorted(por_receta.values()))
    decir(lineas, "\n=== 3. Resenas por receta ===")
    decir(lineas, f"Promedio : {r.mean():.1f} | mediana: {np.median(r):.0f} | minimo / maximo: {r.min()} / {r.max()}")
    if r.min() == r.max():
        decir(lineas, f"ATENCION: todas las recetas tienen exactamente {r.min()} resenas. No es una muestra natural de la actividad:")
        decir(lineas, "  parece un tope del scraping (solo las primeras resenas de cada receta). Conviene decirlo en el informe,")
        decir(lineas, "  porque el recorte favorece a las resenas que el sitio muestra primero (las mas votadas).")
    else:
        fig, ax = preparar_ejes("Resenas por receta", f"{n_i} recetas")
        ax.hist(r, bins=min(30, int(r.max() - r.min() + 1)), color=AZUL, edgecolor=SUPERFICIE, linewidth=1.5)
        ax.set_xlabel("Resenas por receta")
        ax.set_ylabel("Cantidad de recetas")
        guardar(fig, carpeta, "3_resenas_por_receta.png")


def seccion_ratings(inter, lineas, carpeta):
    """4. Distribucion de ratings y rating medio por usuario."""
    n_int = len(inter)
    ratings = Counter(x[2] for x in inter)
    niveles = list(range(0, 6))
    cuentas = [ratings.get(k, 0) for k in niveles]
    decir(lineas, "\n=== 4. Ratings ===")
    for k, c in zip(niveles, cuentas):
        etiqueta = "sin estrellas" if k == 0 else f"{k} estrella(s)"
        decir(lineas, f"  rating {k} ({etiqueta}): {c} ({pct(c, n_int)})")
    positivas = sum(c for k, c in zip(niveles, cuentas) if k >= 4)
    decir(lineas, f"Resenas con 4 o 5 estrellas: {pct(positivas, n_int)}. Con un umbral de 'le gusto' en 4, casi todo cuenta como positivo:")
    decir(lineas, "  el rating casi no discrimina y el recomendador se apoya sobre todo en SI el usuario resenio, no en cuanto le gusto.")
    if ratings.get(0, 0):
        decir(lineas, f"Resenas con rating 0: {ratings[0]}. En food.com un 0 suele ser una resena escrita sin puntuar, no un disgusto;")
        decir(lineas, "  conviene excluirlas o tratarlas como 'sin rating' en el recomendador y en la evaluacion.")

    fig, ax = preparar_ejes(
        f"El {100 * ratings.get(5, 0) / n_int:.0f}% de las resenas tiene 5 estrellas",
        "Cantidad de resenas por rating. El 0 es una resena sin estrellas.")
    barras = ax.bar([str(k) for k in niveles], cuentas, color=AZUL, edgecolor=SUPERFICIE, linewidth=2, width=0.6)
    for b, c in zip(barras, cuentas):
        ax.text(b.get_x() + b.get_width() / 2, c + max(cuentas) * 0.015, f"{100 * c / n_int:.1f}%",
                ha="center", va="bottom", fontsize=10, color=TEXTO)
    ax.set_xlabel("Rating (estrellas)")
    ax.set_ylabel("Resenas")
    ax.set_ylim(0, max(cuentas) * 1.12)
    guardar(fig, carpeta, "4_distribucion_ratings.png")

    # Rating medio por usuario (sin contar los 0)
    suma, cant = Counter(), Counter()
    for u, _, rt, _ in inter:
        if rt and rt > 0:
            suma[u] += rt
            cant[u] += 1
    medios = np.array([suma[u] / cant[u] for u in cant])
    decir(lineas, f"\nRating medio por usuario (sin contar ceros): promedio {medios.mean():.2f}; "
                  f"{(medios >= 4.8).sum()} de {len(medios)} usuarios ({pct((medios >= 4.8).sum(), len(medios))}) promedian 4.8 o mas.")
    fig, ax = preparar_ejes(
        "Casi todos los usuarios puntuan alto",
        "Rating medio de cada usuario, sin contar las resenas sin estrellas.")
    ax.hist(medios, bins=np.arange(3.0, 5.01, 0.1), color=AZUL, edgecolor=SUPERFICIE, linewidth=1.5)
    ax.set_xlabel("Rating medio del usuario")
    ax.set_ylabel("Cantidad de usuarios")
    guardar(fig, carpeta, "5_rating_medio_por_usuario.png")


def seccion_tiempo(inter, lineas, carpeta):
    """5. Reseñas por año."""
    anios = Counter()
    for _, _, _, fecha in inter:
        if fecha and len(fecha) >= 4 and fecha[:4].isdigit():
            anios[int(fecha[:4])] += 1
    if not anios:
        return
    ys = list(range(min(anios), max(anios) + 1))
    cs = [anios.get(y, 0) for y in ys]
    pico = ys[int(np.argmax(cs))]
    decir(lineas, f"\n=== 5. Tiempo ===\nRango de fechas: {min(anios)} a {max(anios)}. Anio con mas resenas: {pico} ({max(cs)}).")
    fig, ax = preparar_ejes(
        f"Las resenas se concentran en {pico}",
        "Resenas por anio de publicacion. Sirve para decidir si conviene un corte temporal en la evaluacion.")
    ax.bar([str(y) for y in ys], cs, color=AZUL, edgecolor=SUPERFICIE, linewidth=1.5, width=0.7)
    ax.tick_params(axis="x", labelrotation=60, labelsize=9)
    ax.set_ylabel("Resenas")
    guardar(fig, carpeta, "6_resenas_por_anio.png")


def seccion_catalogo(con, inter, lineas, carpeta):
    """6. Categorias y autores (necesita ids de 'recetas' alineados con las URLs)."""
    n_i = len({r[1] for r in inter})
    recetas = con.execute("SELECT id, url, category, author_id, author_name FROM recetas").fetchall()
    desalineadas = sum(1 for rid, url, *_ in recetas if id_food_desde_url(url) != rid)
    decir(lineas, "\n=== 6. Categorias y autores ===")
    decir(lineas, f"Recetas en el catalogo: {len(recetas)} de {n_i} con interacciones.")
    if desalineadas > 0 or len(recetas) < n_i:
        decir(lineas, f"SALTEADO: {desalineadas} recetas tienen un id que no coincide con el numero final de su URL, "
                      f"y/o faltan recetas ({len(recetas)} de {n_i}).")
        decir(lineas, "  Corre  python main.py base  para rehacer la base y despues volve a correr el EDA.")
        return

    por_cat = Counter()
    cat_de = {rid: cat for rid, _, cat, _, _ in recetas}
    for _, rid, _, _ in inter:
        por_cat[cat_de.get(rid) or "(sin categoria)"] += 1
    top = por_cat.most_common(15)[::-1]
    decir(lineas, "Categorias con mas resenas: " + ", ".join(f"{c} ({n})" for c, n in top[::-1][:5]))
    fig, ax = preparar_ejes(
        f"'{top[-1][0]}' es la categoria con mas resenas",
        f"Resenas por categoria de receta (las 15 principales de {len(por_cat)}).", alto=5.6)
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", visible=True)
    ax.barh([c for c, _ in top], [n for _, n in top], color=AZUL, edgecolor=SUPERFICIE, linewidth=1.5, height=0.7)
    ax.set_xlabel("Resenas")
    fig.subplots_adjust(left=0.24)
    guardar(fig, carpeta, "7_categorias.png")

    aut_de = {rid: (aid, nom) for rid, _, _, aid, nom in recetas}
    recetas_por_autor = Counter(a for a, _ in aut_de.values() if a is not None)
    n_aut = len(recetas_por_autor)
    top_aut = sum(c for _, c in recetas_por_autor.most_common(10))
    decir(lineas, f"Autores distintos: {n_aut}. Los 10 autores con mas recetas firman {pct(top_aut, len(recetas))} del catalogo.")
    unicas = sum(1 for c in recetas_por_autor.values() if c == 1)
    decir(lineas, f"Autores con una sola receta: {unicas} ({pct(unicas, n_aut)}). El score de 'perfil' por autor tiene poca senal si casi todos firman una sola receta.")


# ---------------------------------------------------------------------------
# Funciones principales
# ---------------------------------------------------------------------------

def hacer_eda(ruta_db=config.DB_APP, carpeta_salida=config.CARPETA_EDA):
    """Corre todas las secciones del EDA y guarda graficos + resumen.txt."""
    if not os.path.exists(ruta_db):
        raise SystemExit(f"No encuentro '{ruta_db}'. Revisa CARPETA_DATOS en config.py.")
    os.makedirs(carpeta_salida, exist_ok=True)

    con = conectar(os.path.abspath(ruta_db), solo_lectura=True)
    inter = con.execute("SELECT id_lector, id_receta, rating, fecha FROM interacciones").fetchall()
    lineas = []  # lo que va al resumen.txt

    seccion_matriz(inter, lineas)
    seccion_usuarios(inter, lineas, carpeta_salida)
    seccion_recetas(inter, lineas, carpeta_salida)
    seccion_ratings(inter, lineas, carpeta_salida)
    seccion_tiempo(inter, lineas, carpeta_salida)
    seccion_catalogo(con, inter, lineas, carpeta_salida)
    con.close()

    ruta_resumen = os.path.join(carpeta_salida, "resumen.txt")
    with open(ruta_resumen, "w", encoding="utf-8") as f:
        f.write("\n".join(lineas) + "\n")
    print(f"\nListo. Resumen en {ruta_resumen}")


def comparar_con_sitio(ruta_db=config.DB_APP):
    """Compara, receta por receta, el promedio que muestra food.com
    (rating_value) con el promedio de las reseñas que bajamos."""
    con = conectar(ruta_db, solo_lectura=True)
    filas = con.execute("""
        SELECT r.id, r.rating_value, r.rating_count, AVG(i.rating), COUNT(*)
          FROM recetas r JOIN interacciones i ON i.id_receta = r.id
         WHERE i.rating > 0 AND r.rating_value IS NOT NULL AND r.rating_count > 0
         GROUP BY r.id
    """).fetchall()
    con.close()
    if not filas:
        raise SystemExit("No hay recetas con rating_value y reseñas para comparar.")

    sitio = [f[1] for f in filas]
    nuestro = [f[3] for f in filas]
    dif = [n - s for n, s in zip(nuestro, sitio)]
    n = len(filas)

    print(f"Recetas comparadas: {n}")
    print(f"Promedio del sitio (rating_value), promedio entre recetas : {st.mean(sitio):.2f}")
    print(f"Promedio de las reseñas que bajamos, entre recetas        : {st.mean(nuestro):.2f}")
    print(f"Diferencia (lo bajado - sitio): media {st.mean(dif):+.2f} | mediana {st.median(dif):+.2f}")
    mayor = sum(1 for d in dif if d > 0.25)
    menor = sum(1 for d in dif if d < -0.25)
    print(f"Recetas donde lo bajado puntua mas de 0.25 por ENCIMA del sitio: {mayor} ({100*mayor/n:.0f}%)")
    print(f"Recetas donde lo bajado puntua mas de 0.25 por DEBAJO del sitio: {menor} ({100*menor/n:.0f}%)")

    # correlacion (a mano, sin numpy)
    ms, mn = st.mean(sitio), st.mean(nuestro)
    num = sum((s - ms) * (x - mn) for s, x in zip(sitio, nuestro))
    den = (sum((s - ms) ** 2 for s in sitio) * sum((x - mn) ** 2 for x in nuestro)) ** 0.5
    if den:
        print(f"Correlacion entre ambos promedios: {num/den:.2f}")

    print("\nComo leerlo:")
    print("- Diferencia cerca de 0: la gente puntua alto de verdad; el scraping no distorsiona mucho.")
    print("- Diferencia claramente positiva: el feed ordenado por likes sobrerrepresenta reseñas muy buenas.")
    print("- Ojo: rating_value incluye valoraciones sin texto, que no bajamos; la comparacion es aproximada.")
