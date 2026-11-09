from flask import Flask, render_template, request, redirect

import recomendador
from categorias import en_castellano

app = Flask(__name__)

# En la pagina las categorias se muestran en castellano: {{ receta["category"]|castellano }}
app.jinja_env.filters["castellano"] = en_castellano

# Con cuantas recetas (valoradas o "me tienta") se pasa de popularidad a EASE
PARA_PERSONALIZAR = recomendador.MAX_VALORADAS_COLD_START + 1

# Mensajes que se muestran arriba de la pagina despues de cada accion
# (llegan como ?aviso=... en la direccion)
AVISOS = {
    "bienvenida": "¡Listo! Ya armamos tus primeras recomendaciones.",
    "valorada": "¡Gracias! Guardamos tu valoración.",
    "guardada": "Guardada. La encontrás en «Ya vistas › Guardadas».",
    "desguardada": "La sacamos de tus guardadas.",
    "descartada": "Listo, no te la vamos a mostrar más.",
    "reset": "Reiniciamos tu historial: arrancás de cero.",
}


def con_aviso(direccion, aviso, nueva=None):
    """Agrega ?aviso=... (y la receta nueva a resaltar) a una direccion."""
    separador = "&" if "?" in direccion else "?"
    direccion = f"{direccion}{separador}aviso={aviso}"
    if nueva:
        direccion += f"&nueva={nueva}"
    return direccion


def direccion_segura(direccion, por_defecto):
    """Solo se vuelve a direcciones de esta misma pagina (que empiezan con
    una sola /). Evita que un link armado mande al usuario a otro sitio."""
    if direccion and direccion.startswith("/") and not direccion.startswith("//"):
        return direccion
    return por_defecto


def datos_de_usuario(id_usuario):
    """Lo que necesitan todas las paginas: nombre y progreso."""
    cant_positivas = len(recomendador.items_positivos(id_usuario))
    return {
        "id_usuario": id_usuario,
        "username": recomendador.obtener_username(id_usuario),
        "cant_positivas": cant_positivas,
        "para_personalizar": PARA_PERSONALIZAR,
        "personalizado": cant_positivas >= PARA_PERSONALIZAR,
    }


# ---------------------------------------------------------------------------
# Entrada
# ---------------------------------------------------------------------------

@app.get("/")
def get_index():
    # Tres fotos de recetas reales para mostrar de que se trata la pagina
    fotos = [r for r in recomendador.top_populares(N=20) if r["primary_image_url"]][:3]
    return render_template("login.html", fotos=fotos)


@app.post("/")
def post_index():
    username = (request.form.get("username") or "").strip()
    if not username:
        return redirect("/")

    id_usuario = recomendador.buscar_usuario_por_nombre(username)
    if id_usuario is None:
        # Usuario nuevo: lo damos de alta y le pedimos que elija algunas recetas
        id_usuario = recomendador.crear_usuario(username)
        return redirect(f"/bienvenida/{id_usuario}")

    return redirect(f"/recomendar/{id_usuario}")


@app.get("/bienvenida/<int:id_usuario>")
def get_bienvenida(id_usuario):
    return render_template(
        "bienvenida.html",
        opciones=recomendador.populares_variadas(N=12),
        **datos_de_usuario(id_usuario),
    )


@app.post("/bienvenida/<int:id_usuario>")
def post_bienvenida(id_usuario):
    for id_receta in request.form.getlist("receta"):
        recomendador.marcar_senal(id_usuario, int(id_receta), "tienta")
    # Con lo que eligio se arma la primera tanda (si eligio 3 o mas, ya es EASE)
    recomendador.recomendar_lote(id_usuario, N=10, nuevo=True)
    return redirect(con_aviso(f"/recomendar/{id_usuario}", "bienvenida"))


# ---------------------------------------------------------------------------
# Recomendaciones
# ---------------------------------------------------------------------------

@app.get("/recomendar/<int:id_usuario>")
def get_recomendar(id_usuario):
    # La tanda de 10 se guarda (lote_actual): volver a esta pagina muestra
    # las mismas recetas. Solo se arma una tanda nueva con "Ver otras 10".
    if request.args.get("nuevas") == "1":
        recomendador.recomendar_lote(id_usuario, N=10, nuevo=True)
        # Se redirige sin ?nuevas=1: si el usuario recarga, no se arma otra.
        return redirect(f"/recomendar/{id_usuario}")

    recetas, algoritmo = recomendador.recomendar_lote(id_usuario, N=10)
    ids_tanda = [r["id"] for r in recetas]

    # "Las más populares" sin repetir las recetas de la tanda
    populares = [r for r in recomendador.top_populares(N=40) if r["id"] not in ids_tanda][:10]

    # El algoritmo usado queda solo para nosotros (consola)
    print(f"[recomendar] usuario={id_usuario} algoritmo={algoritmo}")

    return render_template(
        "recomendaciones.html",
        activa="inicio",
        recetas=recetas,
        populares=populares,
        por_que=recomendador.explicaciones(id_usuario, ids_tanda),
        n_ingredientes=recomendador.cantidad_ingredientes(ids_tanda + [r["id"] for r in populares]),
        guardadas=set(recomendador.items_con_senal(id_usuario, "tienta")),
        aviso=AVISOS.get(request.args.get("aviso")),
        nueva=request.args.get("nueva", type=int),
        volver=f"/recomendar/{id_usuario}",
        **datos_de_usuario(id_usuario),
    )


# ---------------------------------------------------------------------------
# Una receta
# ---------------------------------------------------------------------------

@app.get("/receta/<int:id_usuario>/<int:id_receta>")
def get_receta(id_usuario, id_receta):
    receta = recomendador.obtener_receta(id_receta)
    if receta is None:
        return redirect(f"/recomendar/{id_usuario}")

    return render_template(
        "receta.html",
        receta=receta,
        ingredientes=[i for i in recomendador.obtener_ingredientes(id_receta) if i and i.strip()],
        mi_rating=recomendador.mi_rating(id_usuario, id_receta),
        mi_senal=recomendador.mi_senal(id_usuario, id_receta),
        aviso=AVISOS.get(request.args.get("aviso")),
        volver=f"/receta/{id_usuario}/{id_receta}",
        **datos_de_usuario(id_usuario),
    )


@app.post("/receta/<int:id_usuario>/<int:id_receta>")
def post_receta(id_usuario, id_receta):
    rating = int(request.form.get("rating", 0))
    if rating < 1 or rating > 5:
        return redirect(f"/receta/{id_usuario}/{id_receta}")

    recomendador.insertar_interaccion(id_usuario, id_receta, rating)
    # Solo se reemplaza la receta que valoro; las otras 9 quedan igual.
    # (Si no estaba en su tanda, por ejemplo una popular, la tanda no cambia.)
    nueva = recomendador.reemplazar_en_lote(id_usuario, id_receta)
    return redirect(con_aviso(f"/recomendar/{id_usuario}", "valorada", nueva["id"] if nueva else None))


@app.post("/senal/<int:id_usuario>/<int:id_receta>")
def post_senal(id_usuario, id_receta):
    """Botones rapidos de las tarjetas: "Me tienta" y "No es para mí"."""
    tipo = request.form.get("tipo")
    volver = direccion_segura(request.form.get("volver"), f"/recomendar/{id_usuario}")

    if tipo == "tienta":
        estado = recomendador.marcar_senal(id_usuario, id_receta, "tienta")
        return redirect(con_aviso(volver, "guardada" if estado else "desguardada"))

    if tipo == "no":
        recomendador.marcar_senal(id_usuario, id_receta, "no")
        nueva = recomendador.reemplazar_en_lote(id_usuario, id_receta)
        return redirect(con_aviso(volver, "descartada", nueva["id"] if nueva else None))

    return redirect(volver)


# ---------------------------------------------------------------------------
# Historial y reinicio
# ---------------------------------------------------------------------------

FILTROS = [
    ("todas", "Todas"),
    ("guardadas", "Guardadas"),
    ("pendientes", "Sin valorar"),
    ("valoradas", "Valoradas"),
]


@app.get("/vistas/<int:id_usuario>")
def get_vistas(id_usuario):
    filtro = request.args.get("filtro", "todas")
    if filtro not in dict(FILTROS):
        filtro = "todas"
    recetas = recomendador.recetas_vistas(id_usuario, N=60, filtro=filtro)
    return render_template(
        "vistas.html",
        activa="vistas",
        recetas=recetas,
        filtro=filtro,
        filtros=FILTROS,
        n_ingredientes=recomendador.cantidad_ingredientes([r["id"] for r in recetas]),
        guardadas=set(recomendador.items_con_senal(id_usuario, "tienta")),
        aviso=AVISOS.get(request.args.get("aviso")),
        volver=f"/vistas/{id_usuario}?filtro={filtro}",
        **datos_de_usuario(id_usuario),
    )


@app.post("/reset/<int:id_usuario>")
def post_reset(id_usuario):
    # Es POST (un formulario con confirmacion), no un link: asi no se puede
    # borrar el historial por abrir una direccion o por un navegador que
    # precarga links.
    recomendador.reset_usuario(id_usuario)
    return redirect(con_aviso(f"/recomendar/{id_usuario}", "reset"))


@app.get("/reset/<int:id_usuario>")
def get_reset(id_usuario):
    # Los links viejos a /reset ya no borran nada
    return redirect(f"/recomendar/{id_usuario}")


if __name__ == "__main__":
    app.run(debug=True)
