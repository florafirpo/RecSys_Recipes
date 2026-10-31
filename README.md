# Sistema de recomendación de recetas (food.com)

Recomendador de recetas construido para la materia **Sistemas de Recomendación** (Especialización en Minería de Datos y Descubrimiento del Conocimiento, UBA). Los datos son reseñas reales de [food.com](https://www.food.com), obtenidas con scraping propio. El recomendador se sirve como una aplicación web en PythonAnywhere.

**Autora:** María Florencia Firpo

---

## Cómo está organizado

```
sistema_recomendacion/
├── main.py            punto de entrada: cada paso del pipeline es un subcomando
├── config.py          rutas a los archivos y todos los parámetros (un solo lugar)
├── base_datos.py      funciones de ayuda para SQLite y CSV
├── matriz.py          filtrado p-core y exportación de la matriz usuario x receta
├── dataset.py         arma recetas_app.db y separa train / test
├── recomendador.py    las estrategias de recomendación (la usa también la página web)
├── modelos.py         modelos de filtrado colaborativo: user-kNN y EASE
├── evaluacion.py      métricas offline (hit rate, precision, recall, MRR)
├── eda.py             análisis exploratorio y comparación con el promedio del sitio
├── tests/             tests automáticos (pytest)
├── scraping/          scripts de obtención de datos (ya corridos, se conservan sin cambios)
└── resultados/eda/    gráficos y resumen del análisis exploratorio
```

Cada módulo tiene **funciones**, y `main.py` solo decide cuál llamar. Las bases de datos **no** están en esta carpeta, porque pesan varios GB: se buscan en la carpeta de arriba (ver [Configuración](#configuración)).

## Pipeline

```
 food.com
    │  scraping/1 → 7          (URLs, recetas, comentarios, ingredientes, usuarios)
    ▼
 food_scraping.db  (~298.000 recetas, ~158.000 usuarios, ~573.000 reseñas)
    │  python main.py matriz   (filtrado p-core: sube la densidad de 0,0012 % a ~5 %)
    ▼
 matriz_usuario_item.npz + índices CSV
    │  python main.py base
    ▼
 recetas_app.db  ──────────────►  página web (PythonAnywhere)
    │  python main.py split
    ▼
 recetas_train.db + recetas_test.db
    │  python main.py evaluar
    ▼
 tabla de métricas por estrategia
```

## Inicio rápido

Requiere Python 3.10 o superior.

```bash
python -m venv venv
venv\Scripts\activate            # en Windows  (en Linux/Mac: source venv/bin/activate)
pip install -r requirements.txt

python main.py split             # separa train / test
python main.py evaluar           # compara los recomendadores
```

Para ver todas las opciones: `python main.py --help` o `python main.py matriz --help`.

## Comandos

| Comando | Qué hace | Lee | Escribe |
|---|---|---|---|
| `python main.py matriz` | Prueba varias combinaciones de mínimos y muestra la densidad de cada una | `food_scraping.db` | nada |
| `python main.py matriz 40 10` | Exporta la matriz con p-core (mín. 40 reseñas por usuario, 10 por receta) | `food_scraping.db` | `.npz` + 2 CSV |
| `python main.py matriz 40 10 --tabla-top` | Muestra cómo quedaría recortando a las N recetas más populares | `food_scraping.db` | nada |
| `python main.py matriz 40 10 --top 2000` | Exporta el recorte a las 2000 recetas más populares | `food_scraping.db` | `.npz` + 2 CSV |
| `python main.py base` | Arma la base liviana de la aplicación | `food_scraping.db` + CSV | `recetas_app.db` |
| `python main.py split` | Separa train / test por usuario | `recetas_app.db` | `recetas_train.db`, `recetas_test.db` |
| `python main.py evaluar` | Evalúa las estrategias sobre test | train + test | nada |
| `python main.py eda` | Gráficos y resumen del dataset | `recetas_app.db` | `resultados/eda/` |
| `python main.py sesgo` | Compara nuestras reseñas con el promedio que muestra el sitio | `recetas_app.db` | nada |

> Ojo: `matriz` (con números) y `base` **sobrescriben** los archivos que generan.

## Configuración

Todo se cambia en `config.py`:

- **`CARPETA_DATOS`**: dónde están las bases y los CSV. Por defecto es la carpeta de arriba (`Pagina Food/`). Para usar otra, definí la variable de entorno `RECETAS_DATOS`.
- **`RATING_POSITIVO`** (4): desde qué rating se considera que una receta "le gustó" al usuario.
- **`MAX_VALORADAS_COLD_START`** (2): con esa cantidad de reseñas o menos, el usuario se trata como *cold start*.
- **`FRACCION_TEST`** (0,2), **`MIN_QUE_QUEDAN`** (3), **`SEMILLA`** (42): parámetros de la separación train / test.

## Estrategias de recomendación

| Estrategia | Idea |
|---|---|
| `azar` | Baseline: recetas al azar que el usuario no valoró ni vio |
| `top_n` | Popularidad: suma de ratings de cada receta en `interacciones` (en la evaluación, solo train) |
| `perfil` | Contenido: categorías (peso 0,8) y autores (peso 0,2) de las recetas que le gustaron |
| `recomendar` | Combina las anteriores: *cold start* → `top_n`; con historial → `perfil`, completando con `top_n` |
| `user-kNN` | Filtrado colaborativo: recomienda lo que reseñaron los k usuarios más parecidos (similitud coseno) |
| `EASE` | Modelo lineal receta × receta con fórmula cerrada (Steck, 2019): aprende cuánto "empuja" cada receta reseñada a cada otra |

Los dos modelos colaborativos usan la matriz **binaria** (reseñó / no reseñó). El 97 % de las reseñas tiene 4 o 5 estrellas, así que el rating casi no distingue gustos y la señal útil es qué recetas reseñó cada usuario (*feedback* implícito).

Para sumar un modelo nuevo a la comparación, agregalo en `estrategias_a_evaluar()` dentro de `evaluacion.py`. Cada estrategia recibe un `id_lector` y devuelve una lista de recetas ordenadas de mejor a peor.

### Metodología de evaluación

Split **80/20 por usuario**: a cada usuario se le esconde al azar el 20 % de sus reseñas, elegidas entre las positivas (rating ≥ 4) de recetas del catálogo. Cada usuario conserva al menos 3 reseñas en train. Cada recomendador "aprende" solo con train y se mide cuántas de las recetas escondidas aparecen entre sus 10 recomendaciones.

Con este split quedan 6.196 reseñas en test (mediana de 10 por usuario, mínimo 6) y una mediana de 38 en train.

Resultados actuales (501 usuarios, N = 10; `azar` es el promedio de 20 corridas):

| Estrategia | hit rate@10 | precision@10 | recall@10 | MRR |
|---|---|---|---|---|
| azar | 0,069 | 0,007 | 0,006 | 0,021 |
| top_n | 0,453 | 0,071 | 0,066 | 0,223 |
| perfil | 0,168 | 0,019 | 0,015 | 0,066 |
| recomendar | 0,168 | 0,019 | 0,015 | 0,066 |
| user-kNN (k=50) | 0,497 | 0,078 | 0,071 | 0,238 |
| **EASE (λ=500)** | **0,517** | **0,083** | **0,075** | **0,243** |

**¿Le ganan de verdad a la popularidad?** `python main.py evaluar` también compara cada estrategia contra `top_n` usuario por usuario y calcula un intervalo de confianza del 95 % con *bootstrap* pareado:

| Estrategia | Diferencia en precision@10 vs top_n | IC 95 % | |
|---|---|---|---|
| EASE | +0,012 (+17 %) | [+0,007; +0,016] | significativa |
| user-kNN | +0,007 (+10 %) | [+0,003; +0,012] | significativa |
| perfil | −0,052 | [−0,062; −0,043] | significativa (peor) |

La popularidad es un rival muy fuerte en este dataset, por cómo se armó la muestra (ver Limitaciones). Aun así, los dos modelos colaborativos la superan con diferencias pequeñas pero significativas.

Con más recetas escondidas por usuario es más fácil acertar al menos una, así que el hit rate sube mucho respecto del split anterior. Las métricas de los dos splits **no se comparan entre sí**. Para comparar modelos conviene mirar sobre todo precision@10 y MRR.

Como todos los usuarios de la muestra tienen 30 reseñas o más, `recomendar` siempre usa `perfil` y por eso rinde lo mismo que `perfil`, por debajo de `top_n`.

### Historial de cambios en las métricas

Estas mediciones se hicieron con el split anterior (2 reseñas por usuario en test), antes de pasar al 80/20.

| Cambio | Estrategia | hit rate@10 | MRR | Comentario |
|---|---|---|---|---|
| Versión original | perfil | 0,032 | 0,008 | `JOIN` con el perfil de autor: solo recomendaba recetas de autores ya valorados |
| `LEFT JOIN` (categoría y/o autor) | perfil | 0,028 | 0,010 | Arreglo lógico correcto, pero las métricas casi no se mueven |
| Versión original | top_n | 0,114 | 0,044 | Popularidad según `rating_value × rating_count` de food.com (incluye las reseñas de test: leakage) |
| Popularidad calculada con train | top_n | 0,130 | 0,047 | Sin leakage, y además **mejora** |
| Split 80/20 por usuario | todas | — | — | Nueva línea base: ver la tabla de resultados actuales |

¿Por qué `perfil` no mejoró? Con el arreglo, cada usuario tiene una mediana de 1.276 recetas candidatas (de 1.855), porque la categoría es una señal muy gruesa: casi todo el catálogo cae en alguna categoría que le gustó. Probamos desempatar por popularidad en train y tampoco mejoró (hit rate 0,024). La limitación es del modelo de contenido con solo categoría y autor, no un error de código. Es un argumento para pasar a filtrado colaborativo o a usar ingredientes.

¿Por qué `top_n` mejoró al sacarle el leakage? Lo esperable era que bajara. La explicación más probable es que la popularidad dentro de la muestra (501 usuarios muy activos) describe mejor sus gustos que la popularidad de todo el sitio. El número nuevo es el que vale como baseline.

## Bugs corregidos

Cada uno tiene un test de regresión en `tests/` para que no vuelva a aparecer.

1. **`perfil` descartaba recetas de autores nuevos**: unía el perfil de autor con `JOIN` en lugar de `LEFT JOIN`. Ver el historial de métricas.
2. **Leakage en `top_n`**: usaba `rating_value` y `rating_count` publicados por food.com, que incluyen las reseñas escondidas en test. Ahora la popularidad se calcula con `interacciones`. La sección "Las más populares" de la página (`top_populares`) usa el mismo criterio.
3. **Reseñas repetidas en la matriz**: si un usuario reseñaba dos veces la misma receta, el p-core la contaba dos veces y `csr_matrix` sumaba los ratings. Ahora se deja solo la primera reseña, igual que hace `dataset.py`. En la matriz actual no pasaba (todas las celdas están entre 1 y 5).

## Limitaciones

- **Selección de la muestra**: el filtrado p-core se hace con todas las reseñas, antes de separar train y test. Una receta puede estar en el catálogo gracias a reseñas que después quedan en test. Es una práctica habitual en la literatura, pero conviene mencionarla.
- **Hiperparámetros**: `K_VECINOS` y `LAMBDA_EASE` (en `config.py`) salieron de una exploración rápida sobre el split anterior, no de un conjunto de validación separado. Lo correcto sería ajustarlos con una validación tomada de train.
- **Dataset** (ver `resultados/eda/resumen.txt`): el 81 % de las reseñas tiene 5 estrellas, y el feed de food.com viene ordenado por "más likes", así que las primeras reseñas de cada receta están sobrerrepresentadas.

## Tests

```bash
python -m pytest            # o, con más detalle:  python -m pytest -v
```

Los tests usan bases de juguete en carpetas temporales: no tocan los datos reales. Cubren:

- **Separación train / test (anti-leakage)**: ninguna reseña queda en los dos lados, test solo tiene reseñas positivas y del catálogo, la separación es reproducible y no modifica la base original.
- **Filtrado p-core**: mínimos, efecto cascada y densidad.
- **Métricas**: valores calculados a mano, y que la comparación con *bootstrap* detecte una mejora clara.
- **Modelos colaborativos**: matriz binaria, que no repitan recetas ya reseñadas, que EASE no recomiende una receta por sí misma y que un usuario desconocido reciba popularidad.
- **Recomendador**: no repite recetas valoradas ni vistas, la evaluación no escribe en la base y el cold start funciona.

## Despliegue en PythonAnywhere

La página web importa `recomendador.py`, que a su vez necesita `config.py`. Subí los dos archivos junto con la aplicación y apuntá a la base con una variable de entorno: `RECETAS_DB` (ruta completa a `recetas_app.db`) o `RECETAS_DATOS` (carpeta).

## Scraping

Los scripts de `scraping/` se corrieron una sola vez para construir `food_scraping.db` y se conservan sin cambios para documentar cómo se obtuvieron los datos. Usan rutas relativas, así que se corren desde la carpeta de datos, por ejemplo `cd "Pagina Food"` y después `python sistema_recomendacion/scraping/5_resumen_final.py`. Todos son resumibles y respetan pausas entre pedidos para no sobrecargar el sitio.
