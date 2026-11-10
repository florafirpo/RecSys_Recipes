"""
Traduccion de ingredientes para el buscador.

Los ingredientes de food.com estan en ingles ("chicken", "potato"), pero la
gente va a buscar en castellano ("pollo", "papa"). Aca se traduce lo que
escribio el usuario a los terminos en ingles que hay que buscar. Si escribe
algo que no esta en la lista, se busca tal cual (sirve si lo escribe en
ingles).
"""

import unicodedata

INGREDIENTES = {
    "pollo": ["chicken"], "pechuga": ["chicken breast"], "carne": ["beef", "steak"],
    "carne picada": ["ground beef"], "cerdo": ["pork"], "jamon": ["ham"], "panceta": ["bacon"],
    "pavo": ["turkey"], "cordero": ["lamb"], "salchicha": ["sausage"], "chorizo": ["chorizo", "sausage"],
    "pescado": ["fish"], "atun": ["tuna"], "salmon": ["salmon"], "camaron": ["shrimp"],
    "langostino": ["shrimp"], "cangrejo": ["crab"],
    "huevo": ["egg"], "leche": ["milk"], "manteca": ["butter"], "crema": ["cream", "heavy cream"],
    "crema agria": ["sour cream"], "queso": ["cheese"], "queso crema": ["cream cheese"],
    "mozzarella": ["mozzarella"], "parmesano": ["parmesan"], "ricota": ["ricotta"], "yogur": ["yogurt"],
    "harina": ["flour"], "azucar": ["sugar"], "miel": ["honey"], "chocolate": ["chocolate"],
    "cacao": ["cocoa"], "vainilla": ["vanilla"], "canela": ["cinnamon"], "avena": ["oats"],
    "arroz": ["rice"], "fideos": ["pasta", "noodles", "spaghetti"], "pasta": ["pasta"], "pan": ["bread"],
    "papa": ["potato"], "batata": ["sweet potato"], "tomate": ["tomato"], "cebolla": ["onion"],
    "ajo": ["garlic"], "zanahoria": ["carrot"], "morron": ["bell pepper"], "pimiento": ["bell pepper"],
    "choclo": ["corn"], "maiz": ["corn"], "espinaca": ["spinach"], "brocoli": ["broccoli"],
    "coliflor": ["cauliflower"], "repollo": ["cabbage"], "lechuga": ["lettuce"], "pepino": ["cucumber"],
    "zapallo": ["pumpkin", "squash"], "calabaza": ["pumpkin", "squash"], "zucchini": ["zucchini"],
    "berenjena": ["eggplant"], "apio": ["celery"], "arvejas": ["peas"], "hongos": ["mushroom"],
    "champinones": ["mushroom"], "palta": ["avocado"], "porotos": ["beans"], "lentejas": ["lentils"],
    "garbanzos": ["chickpeas", "garbanzo"],
    "limon": ["lemon"], "lima": ["lime"], "naranja": ["orange"], "manzana": ["apple"], "banana": ["banana"],
    "frutilla": ["strawberry", "strawberries"], "arandanos": ["blueberries", "cranberries"],
    "frambuesa": ["raspberry", "raspberries"], "durazno": ["peach"], "pera": ["pear"], "coco": ["coconut"],
    "mani": ["peanut"], "mantequilla de mani": ["peanut butter"], "nuez": ["walnut", "pecan"],
    "nueces": ["walnuts", "pecans"], "almendra": ["almond"], "pasas": ["raisins"],
    "aceite de oliva": ["olive oil"], "mayonesa": ["mayonnaise"], "mostaza": ["mustard"],
    "salsa de soja": ["soy sauce"], "vinagre": ["vinegar"], "perejil": ["parsley"], "albahaca": ["basil"],
    "oregano": ["oregano"], "comino": ["cumin"], "pimenton": ["paprika"], "jengibre": ["ginger"],
    "romero": ["rosemary"], "tomillo": ["thyme"], "curry": ["curry"], "cilantro": ["cilantro"],
}


def sin_acentos(texto):
    texto = unicodedata.normalize("NFD", texto.lower().strip())
    return "".join(c for c in texto if unicodedata.category(c) != "Mn")


def terminos_de_busqueda(texto):
    """'Pollo' -> ['chicken']. Si no esta en la lista, se busca lo que escribio."""
    clave = sin_acentos(texto)
    if not clave:
        return []
    if clave in INGREDIENTES:
        return INGREDIENTES[clave]
    # plural simple: "papas" -> "papa", "tomates" -> "tomate"
    for sin_plural in (clave[:-1], clave[:-2]):
        if sin_plural in INGREDIENTES:
            return INGREDIENTES[sin_plural]
    return [clave]
