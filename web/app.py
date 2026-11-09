from flask import Flask, render_template, request, redirect
import recomendador

app = Flask(__name__)


@app.get("/")
def get_index():
    return render_template("login.html")


@app.post("/")
def post_index():
    username = (request.form.get("username") or "").strip()

    if not username:
        return redirect("/")

    id_usuario = recomendador.buscar_usuario_por_nombre(username)
    if id_usuario is None:
        # No existe todavia -> lo damos de alta como usuario nuevo.
        id_usuario = recomendador.crear_usuario(username)

    return redirect(f"/recomendar/{id_usuario}")


@app.get("/recomendar/<int:id_usuario>")
def get_recomendar(id_usuario):
    # La tanda de 10 se guarda (lote_actual): volver a esta pagina muestra
    # las mismas recetas. Solo se arma una tanda nueva cuando el usuario
    # aprieta "Ver otras 10" (?nuevas=1).
    if request.args.get("nuevas") == "1":
        recomendador.recomendar_lote(id_usuario, N=10, nuevo=True)
        # Se redirige a la misma pagina sin ?nuevas=1: asi, si el usuario
        # recarga, no se arma otra tanda.
        return redirect(f"/recomendar/{id_usuario}")
    recetas_recomendadas, algoritmo = recomendador.recomendar_lote(id_usuario, N=10)
    recetas_populares = recomendador.top_populares(N=10)

    cant_vistos = len(recomendador.items_vistos(id_usuario))
    cant_valorados = len(recomendador.items_valorados(id_usuario))

    # El algoritmo usado queda solo para nosotros (consola), no se le
    # muestra al usuario -- a la gente no le importa como lo armamos.
    print(f"[recomendar] usuario={id_usuario} algoritmo={algoritmo}")

    return render_template(
        "recomendaciones.html",
        cant_vistos=cant_vistos,
        cant_valorados=cant_valorados,
        recetas_recomendadas=recetas_recomendadas,
        recetas_populares=recetas_populares,
        id_usuario=id_usuario,
        username=recomendador.obtener_username(id_usuario),
    )


@app.get("/receta/<int:id_usuario>/<int:id_receta>")
def get_receta(id_usuario, id_receta):
    receta = recomendador.obtener_receta(id_receta)
    if receta is None:
        return redirect(f"/recomendar/{id_usuario}")

    ingredientes = recomendador.obtener_ingredientes(id_receta)

    return render_template(
        "receta.html",
        receta=receta,
        ingredientes=ingredientes,
        id_usuario=id_usuario,
        username=recomendador.obtener_username(id_usuario),
    )


@app.post("/receta/<int:id_usuario>/<int:id_receta>")
def post_receta(id_usuario, id_receta):
    rating = int(request.form.get("rating", 0))
    if rating > 0:
        recomendador.insertar_interaccion(id_usuario, id_receta, rating)
        # Solo se reemplaza la receta que valoro; las otras 9 quedan igual.
        # (Si la receta no estaba en su tanda, por ejemplo una de las
        # populares, la tanda no cambia.)
        recomendador.reemplazar_en_lote(id_usuario, id_receta)

    return redirect(f"/recomendar/{id_usuario}")


@app.get("/vistas/<int:id_usuario>")
def get_vistas(id_usuario):
    # Historial: las recetas que ya se le mostraron, para volver a verlas
    return render_template(
        "vistas.html",
        recetas=recomendador.recetas_vistas(id_usuario, N=60),
        id_usuario=id_usuario,
        username=recomendador.obtener_username(id_usuario),
    )


@app.get("/reset/<int:id_usuario>")
def get_reset(id_usuario):
    recomendador.reset_usuario(id_usuario)
    return redirect(f"/recomendar/{id_usuario}")


if __name__ == "__main__":
    app.run(debug=True)
