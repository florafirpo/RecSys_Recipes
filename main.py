"""
Punto de entrada del proyecto. Cada paso del pipeline es un subcomando:

    python main.py matriz                      explora combinaciones de minimos (no escribe nada)
    python main.py matriz 40 10                exporta la matriz con p-core (40, 10)
    python main.py matriz 40 10 --tabla-top    muestra como quedaria recortando a las N recetas mas populares
    python main.py matriz 40 10 --top 2000     exporta el recorte a las 2000 recetas mas populares
    python main.py base                        arma recetas_app.db a partir de la matriz exportada
    python main.py split                       separa recetas_app.db en train y test (80/20 por usuario, al azar)
    python main.py split --temporal 2012-01-01 corte por fecha: train = antes, test = desde esa fecha
    python main.py evaluar                     compara los recomendadores sobre test
    python main.py eda                         graficos y resumen de recetas_app.db
    python main.py sesgo                       compara nuestras reseñas con el promedio del sitio

Orden habitual: matriz -> base -> split -> evaluar.
Las rutas y los parametros se cambian en config.py.
"""

import argparse

import config


def comando_matriz(args):
    import matriz

    interacciones = matriz.cargar_interacciones(config.DB_SCRAPING)

    if len(args.minimos) != 2:
        matriz.explorar(interacciones, config.COMBINACIONES_A_PROBAR)
        print("\nPara exportar: python main.py matriz <min_usuario> <min_item>   (ejemplo: python main.py matriz 40 10)")
        print("Ver el recorte por popularidad: python main.py matriz 40 10 --tabla-top")
        print("Exportarlo:                     python main.py matriz 40 10 --top 2000")
        return

    min_u, min_i = args.minimos
    if args.tabla_top:
        matriz.tabla_top(interacciones, min_u, min_i, config.TAMANIOS_TOP)
        return

    filas = matriz.filtrar_por_core(interacciones, min_u, min_i)
    if args.top and filas:
        filas = matriz.recortar_top_items(filas, args.top, min_u, min_i)
    if not filas:
        print("Con esos minimos no sobrevive nada: NO se escribio ningun archivo.")
        return
    matriz.exportar_filas(filas, config.NPZ_MATRIZ, config.CSV_USUARIOS, config.CSV_ITEMS)


def comando_base(args):
    import dataset
    dataset.armar_base_app()


def comando_split(args):
    import dataset
    if args.temporal:
        dataset.separar_train_test_temporal(args.temporal)
    else:
        dataset.separar_train_test()


def comando_evaluar(args):
    import evaluacion
    evaluacion.evaluar_todo()


def comando_eda(args):
    import eda
    eda.hacer_eda(args.db, args.salida)


def comando_sesgo(args):
    import eda
    eda.comparar_con_sitio(args.db)


def crear_parser():
    parser = argparse.ArgumentParser(description="Sistema de recomendacion de recetas (food.com)")
    sub = parser.add_subparsers(dest="comando", required=True)

    p = sub.add_parser("matriz", help="filtrado p-core y exportacion de la matriz usuario x receta")
    p.add_argument("minimos", nargs="*", type=int, help="min_usuario min_item (sin numeros: solo explora)")
    p.add_argument("--top", type=int, default=None, help="quedarse solo con las N recetas mas populares")
    p.add_argument("--tabla-top", action="store_true", help="mostrar como quedaria con distintos N")
    p.set_defaults(funcion=comando_matriz)

    p = sub.add_parser("base", help="arma recetas_app.db con el subconjunto de la matriz")
    p.set_defaults(funcion=comando_base)

    p = sub.add_parser("split", help="separa recetas_app.db en train y test")
    p.add_argument("--temporal", metavar="AAAA-MM-DD", default=None, help="corte por fecha en lugar de al azar")
    p.set_defaults(funcion=comando_split)

    p = sub.add_parser("evaluar", help="evalua los recomendadores contra test")
    p.set_defaults(funcion=comando_evaluar)

    p = sub.add_parser("eda", help="analisis exploratorio de recetas_app.db")
    p.add_argument("--db", default=config.DB_APP)
    p.add_argument("--salida", default=config.CARPETA_EDA)
    p.set_defaults(funcion=comando_eda)

    p = sub.add_parser("sesgo", help="nuestras reseñas vs. el promedio del sitio")
    p.add_argument("--db", default=config.DB_APP)
    p.set_defaults(funcion=comando_sesgo)

    return parser


def main():
    args = crear_parser().parse_args()
    args.funcion(args)


if __name__ == "__main__":
    main()
