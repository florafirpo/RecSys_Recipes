"""
Configuracion del proyecto: rutas a los archivos y parametros.

Todo lo que antes estaba repetido arriba de cada script (DB_PATH,
RATING_POSITIVO, la semilla, etc.) vive aca, en un solo lugar. Si queres
cambiar un parametro, lo cambias aca y lo toman todos los modulos.
"""

import os

# ---------------------------------------------------------------------------
# Carpetas
# ---------------------------------------------------------------------------

# Carpeta donde esta este archivo (el codigo del proyecto)
CARPETA_PROYECTO = os.path.dirname(os.path.abspath(__file__))

# Carpeta donde estan las bases (.db) y los CSV. Por defecto es la carpeta
# de arriba ("Pagina Food"), porque las bases pesan varios GB y no se
# entregan junto con el codigo. Para usar otra carpeta (por ejemplo en
# PythonAnywhere) se define la variable de entorno RECETAS_DATOS.
CARPETA_DATOS = os.environ.get("RECETAS_DATOS", os.path.dirname(CARPETA_PROYECTO))

# Graficos y resumenes que genera el proyecto (estos si se entregan)
CARPETA_RESULTADOS = os.path.join(CARPETA_PROYECTO, "resultados")
CARPETA_EDA = os.path.join(CARPETA_RESULTADOS, "eda")

# ---------------------------------------------------------------------------
# Archivos de datos
# ---------------------------------------------------------------------------

DB_SCRAPING = os.path.join(CARPETA_DATOS, "food_scraping.db")  # base completa del scraping
DB_APP = os.path.join(CARPETA_DATOS, "recetas_app.db")         # base liviana para la pagina
DB_TRAIN = os.path.join(CARPETA_DATOS, "recetas_train.db")     # copia de DB_APP sin las reviews de test
DB_TEST = os.path.join(CARPETA_DATOS, "recetas_test.db")       # solo las reviews reservadas

NPZ_MATRIZ = os.path.join(CARPETA_DATOS, "matriz_usuario_item.npz")
CSV_USUARIOS = os.path.join(CARPETA_DATOS, "matriz_usuarios_index.csv")
CSV_ITEMS = os.path.join(CARPETA_DATOS, "matriz_items_index.csv")

# ---------------------------------------------------------------------------
# Parametros del recomendador
# ---------------------------------------------------------------------------

# A partir de que rating (1 a 5 estrellas) consideramos que "le gusto"
RATING_POSITIVO = 4

# Con esta cantidad de recetas valoradas o menos, el usuario es "cold start"
# y se le recomienda por popularidad
MAX_VALORADAS_COLD_START = 2

# Cuantas recetas se recomiendan por tanda
N_RECOMENDACIONES = 10

# Hiperparametros de los modelos colaborativos (modelos.py)
K_VECINOS = 50       # user-kNN: cuantos usuarios parecidos se miran
LAMBDA_EASE = 500    # EASE: regularizacion

# ---------------------------------------------------------------------------
# Parametros de la matriz (filtrado p-core)
# ---------------------------------------------------------------------------

# Combinaciones (min_usuario, min_item) que se prueban en modo exploracion.
# Sin reseñas de 0 estrellas. Con historiales completos de usuarios (script 22)
# se pueden usar minimos mas altos: un compañero llego al 5,49% con 80/80.
COMBINACIONES_A_PROBAR = [
    (20, 8), (25, 10), (30, 10), (35, 10), (40, 10), (45, 10),
    (30, 15), (40, 15), (50, 15), (50, 20), (60, 20), (60, 30),
    (80, 20), (80, 40), (80, 80), (100, 50),
]

# Grillas que prueba  python main.py matriz --densidad-minima 0.02
GRILLA_MIN_USUARIO = (5, 8, 10, 15, 20, 25, 30)
GRILLA_MIN_ITEM = (3, 5, 8, 10)
# Recorte a las N recetas mas populares (None = sin recorte). Es lo que mas sube
# la densidad: la base de 501 usuarios y 3,34% salio de (30, 10) con recorte.
GRILLA_TOP = (None, 1000, 1500, 2000, 2500, 3000, 4000)

# Tamaños de recorte que se muestran con --tabla-top
TAMANIOS_TOP = (1000, 1500, 2000, 2500, 3000, 3500)

# ---------------------------------------------------------------------------
# Parametros de la separacion train / test y de la evaluacion
# ---------------------------------------------------------------------------

FRACCION_TEST = 0.2       # que parte de las reviews de cada usuario va a test (80/20 por usuario)
MIN_QUE_QUEDAN = 3        # minimo de reviews que le dejamos en train (para que no caiga en cold start)
SEMILLA = 42              # fija el azar, asi la separacion es reproducible

REPETICIONES_AZAR = 20    # el recomendador al azar varia en cada corrida: promediamos varias

# ---------------------------------------------------------------------------
# Recomendador en dos etapas (dos_etapas.py)
# ---------------------------------------------------------------------------

K_CAND_EASE = 100
K_CAND_USER_KNN = 100
K_CAND_RECIENTES = 50
K_CAND_AUTOR = 30
DIAS_VENTANA_RECIENTE = 730   # "recientes" = los ultimos 2 años (despues de 2011 hay poca actividad)

# Corte temporal interno para entrenar el ranking. Con el split temporal de
# 2012 (train = hasta 2011), el ranking aprende con lo reseñado en 2010-2011.
CORTE_RANKER = "2010-01-01"
