"""
Script 21 - ¿Food.com tiene una direccion que devuelva las reseñas de UN usuario?

Idea (como hizo un compañero con vinos): en vez de bajar las reseñas receta
por receta (5 por pedido), bajar el historial completo de los usuarios mas
activos. Para eso necesitamos una direccion que devuelva las reseñas de un
usuario. Este script prueba varias candidatas con el usuario que mas reseñas
tiene en tu base y te dice cual responde con reseñas.

Hace pocos pedidos (unos 20), con pausas. Solo LEE la base, no modifica nada.
Guarda todo lo que imprime en salida_endpoint_usuario.txt.

Uso:  python probar_endpoint_usuario.py
      python probar_endpoint_usuario.py --member 123456   (probar con otro usuario)
"""
import argparse
import json
import sqlite3
import sys
import time

import requests

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

CANDIDATAS = [
    "https://api.food.com/external/v1/members/{id}/feed/reviews?pn=1",
    "https://api.food.com/external/v1/members/{id}/feed/reviews?pn=1&size=100",
    "https://api.food.com/external/v1/members/{id}/reviews?pn=1",
    "https://api.food.com/external/v1/users/{id}/feed/reviews?pn=1",
    "https://api.food.com/external/v1/members/{id}/feed?pn=1",
    "https://api.food.com/external/v1/members/{id}",
    "https://www.food.com/user/{id}/reviews/as-json",
    "https://www.food.com/user/{id}/as-json",
    "https://www.food.com/user/{id}/reviews?pn=2",
]


def buscar_resenas(obj):
    """Busca recursivamente listas de dicts que parezcan reseñas (con 'rating' y alguna receta)."""
    hallados = []
    if isinstance(obj, dict):
        if "rating" in obj and any(k in obj for k in ("recipeId", "recipe", "recipeUrl", "recipeName", "contentId")):
            hallados.append(obj)
        for v in obj.values():
            hallados.extend(buscar_resenas(v))
    elif isinstance(obj, list):
        for v in obj:
            hallados.extend(buscar_resenas(v))
    return hallados


def pedir_resenas(url):
    """Devuelve (lista de reseñas, total si viene, None si fallo)."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        data = r.json()
    except (requests.exceptions.RequestException, ValueError):
        return None, None
    total = data.get("total") if isinstance(data, dict) else None
    if total is None and isinstance(data, dict):
        total = (data.get("data") or {}).get("total")
    return buscar_resenas(data), total


def probar_paginacion(url_ok):
    """Con la direccion que funciono, prueba cuantas reseñas trae por pagina,
    si acepta pedir mas por pagina, y si la pagina 2 trae reseñas distintas."""
    base = url_ok.split("?")[0]
    print("\n--- Paginacion ---")
    pag1, total = pedir_resenas(base + "?pn=1")
    time.sleep(2)
    if not pag1:
        print("  No pude repetir la pagina 1.")
        return
    ids1 = {x.get("id") for x in pag1}
    print(f"  pagina 1: {len(pag1)} reseñas | total que informa: {total}")
    pag2, _ = pedir_resenas(base + "?pn=2")
    time.sleep(2)
    if pag2:
        nuevas = len({x.get("id") for x in pag2} - ids1)
        print(f"  pagina 2: {len(pag2)} reseñas, {nuevas} distintas de la pagina 1")
    else:
        print("  pagina 2: sin reseñas")
    for nombre in ("size", "pageSize", "limit", "per_page"):
        for valor in (100, 50):
            r, _ = pedir_resenas(f"{base}?pn=1&{nombre}={valor}")
            time.sleep(2)
            cant = len(r) if r else 0
            print(f"  pn=1&{nombre}={valor}: {cant} reseñas")
            if cant > len(pag1):
                print(f"  --> acepta '{nombre}': se pueden pedir {cant} por pagina")
                return
    print("  No acepta pedir mas reseñas por pagina (se queda con las de la pagina 1).")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="food_scraping.db")
    ap.add_argument("--member", type=int, default=None)
    args = ap.parse_args()

    if args.member:
        member, cant = args.member, "?"
    else:
        con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
        member, cant = con.execute("""
            SELECT member_id, COUNT(*) FROM comentarios WHERE member_id IS NOT NULL
            GROUP BY member_id ORDER BY COUNT(*) DESC LIMIT 1
        """).fetchone()
        con.close()
    print(f"Probando con el usuario {member} (tiene {cant} reseñas en tu base)")
    print(f"Su perfil: https://www.food.com/user/{member}\n")

    encontradas = []
    for plantilla in CANDIDATAS:
        url = plantilla.format(id=member)
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
        except requests.exceptions.RequestException as e:
            print(f"  ERROR DE RED  {url}\n                {e}")
            time.sleep(2)
            continue

        tipo = r.headers.get("Content-Type", "")
        resumen = f"HTTP {r.status_code}  {tipo.split(';')[0]:<18} {len(r.content):>8} bytes"
        resenas = []
        claves = ""
        if r.status_code == 200 and "json" in tipo:
            try:
                data = r.json()
                resenas = buscar_resenas(data)
                if isinstance(data, dict):
                    claves = "claves: " + ", ".join(list(data.keys())[:8])
                    total = data.get("total") or (data.get("data") or {}).get("total")
                    if total:
                        claves += f" | total={total}"
            except ValueError:
                pass
        marca = f"  <-- {len(resenas)} reseñas" if resenas else ""
        print(f"  {resumen}  {url}{marca}")
        if claves:
            print(f"                {claves}")
        if resenas:
            encontradas.append((url, resenas))
        time.sleep(2)

    print()
    if not encontradas:
        print("Ninguna candidata devolvio reseñas en JSON.")
        print("Siguiente paso: abrir el perfil del usuario en el navegador, ir a la pestaña de reseñas,")
        print("y con F12 > Red (Network) ver que direccion pide la pagina al bajar mas reseñas.")
        return

    url, resenas = encontradas[0]
    print(f"FUNCIONA: {url}")
    probar_paginacion(url)
    print(f"Devuelve {len(resenas)} reseñas por pedido. Ejemplo (sin textos largos):")
    ejemplo = {k: (v[:60] + "...") if isinstance(v, str) and len(v) > 60 else v for k, v in resenas[0].items()}
    print(json.dumps(ejemplo, indent=2, ensure_ascii=False)[:1500])
    with open("endpoint_usuario_muestra.json", "w", encoding="utf-8") as f:
        json.dump(resenas[:5], f, indent=2, ensure_ascii=False)
    print("\nGuarde 5 reseñas de muestra en endpoint_usuario_muestra.json")


class Duplicar:
    """Escribe a la vez en la pantalla y en un archivo."""
    def __init__(self, *destinos):
        self.destinos = destinos
    def write(self, texto):
        for d in self.destinos:
            d.write(texto)
    def flush(self):
        for d in self.destinos:
            d.flush()


if __name__ == "__main__":
    with open("salida_endpoint_usuario.txt", "w", encoding="utf-8") as archivo:
        sys.stdout = Duplicar(sys.__stdout__, archivo)
        main()
        sys.stdout = sys.__stdout__
    print("\n(Todo lo de arriba quedo guardado en salida_endpoint_usuario.txt)")
