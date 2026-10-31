"""
Fase 1: Obtener todas las URLs de recetas de food.com usando su sitemap XML.

Qué hace:
1. Descarga el sitemap.xml principal (el "índice"), que lista 24 sub-sitemaps.
2. Descarga cada sub-sitemap (vienen comprimidos en .gz).
3. Descomprime y parsea el XML de cada uno para sacar todas las URLs.
4. Se queda solo con las URLs que son recetas (contienen "/recipe/").
5. Guarda todo en un archivo CSV: recetas_urls.csv
"""

import csv
import gzip
import time
import xml.etree.ElementTree as ET

import requests

URL_SITEMAP_PRINCIPAL = "https://www.food.com/sitemap.xml"
ARCHIVO_SALIDA = "recetas_urls.csv"
PAUSA_ENTRE_DESCARGAS = 1  # segundos, para no saturar el servidor
TIMEOUT = 30  # segundos, para que un pedido colgado no frene todo el script

# Food.com usa el namespace estándar de sitemaps.org, hay que declararlo para parsear bien
NAMESPACE = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

# Le ponemos un User-Agent "normal" de navegador, algunos sitios bloquean
# pedidos que no tengan uno (aunque tengas autorización, es buena práctica)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}


def descargar_xml(sesion, url, comprimido=False):
    """Descarga un XML (opcionalmente en .gz) y devuelve su elemento raíz."""
    respuesta = sesion.get(url, timeout=TIMEOUT)
    respuesta.raise_for_status()  # si hubo error HTTP, esto tira una excepción

    contenido = respuesta.content
    if comprimido:
        contenido = gzip.decompress(contenido)

    return ET.fromstring(contenido)


def extraer_locs(raiz, etiqueta):
    """Devuelve el texto de <loc> dentro de cada elemento <etiqueta> del sitemap."""
    return [
        elemento.find("sm:loc", NAMESPACE).text
        for elemento in raiz.findall(f"sm:{etiqueta}", NAMESPACE)
    ]


def obtener_lista_de_sub_sitemaps(sesion, url_sitemap_principal):
    """Descarga el sitemap.xml principal y devuelve la lista de URLs de sub-sitemaps."""
    raiz = descargar_xml(sesion, url_sitemap_principal)
    return extraer_locs(raiz, "sitemap")


def obtener_urls_de_un_sub_sitemap(sesion, url_sub_sitemap):
    """Descarga un sub-sitemap .gz, lo descomprime y devuelve todas sus URLs."""
    raiz = descargar_xml(sesion, url_sub_sitemap, comprimido=True)
    return extraer_locs(raiz, "url")


def guardar_csv(urls, ruta):
    """Guarda las URLs en un CSV simple, una por fila."""
    with open(ruta, "w", newline="", encoding="utf-8") as archivo_csv:
        escritor = csv.writer(archivo_csv)
        escritor.writerow(["url_receta"])
        escritor.writerows([url] for url in urls)


def main():
    # Una sola sesión reutiliza la conexión entre descargas
    with requests.Session() as sesion:
        sesion.headers.update(HEADERS)

        print("Descargando lista de sub-sitemaps...")
        sub_sitemaps = obtener_lista_de_sub_sitemaps(sesion, URL_SITEMAP_PRINCIPAL)
        print(f"Encontrados {len(sub_sitemaps)} sub-sitemaps.")

        # Usamos un set para sacar duplicados sobre la marcha
        urls_de_recetas = set()

        for i, url_sub in enumerate(sub_sitemaps, start=1):
            print(f"Procesando sub-sitemap {i}/{len(sub_sitemaps)}: {url_sub}")

            todas_las_urls = obtener_urls_de_un_sub_sitemap(sesion, url_sub)

            # Nos quedamos solo con las que son recetas
            recetas_de_este_sitemap = [u for u in todas_las_urls if "/recipe/" in u]
            urls_de_recetas.update(recetas_de_este_sitemap)

            print(f"  -> {len(recetas_de_este_sitemap)} recetas encontradas en este sitemap")

            time.sleep(PAUSA_ENTRE_DESCARGAS)

    urls_ordenadas = sorted(urls_de_recetas)
    print(f"\nTotal de recetas únicas encontradas: {len(urls_ordenadas)}")

    guardar_csv(urls_ordenadas, ARCHIVO_SALIDA)
    print(f"Guardado en {ARCHIVO_SALIDA}")


if __name__ == "__main__":
    main()
