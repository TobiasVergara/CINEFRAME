#!/usr/bin/env python3
"""
CineFrame — Daily movie generator
Llamado cada noche por GitHub Actions.
Usa Claude para elegir 5 películas y Wikipedia para obtener imágenes de fotogramas.
"""

import os
import json
import datetime
import urllib.request
import urllib.parse
import re
import sys

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
JSON_PATH = os.path.join(os.path.dirname(__file__), "peliculas.json")

NATIONALITIES = [
    "Americana", "Española", "Francesa", "Italiana", "Británica",
    "Alemana", "Japonesa", "Coreana", "Mexicana", "Argentina",
    "Sueca", "Danesa", "Rusa / Soviética", "China", "Iraní",
    "India", "Australiana", "Canadiense", "Belga", "Polaca"
]

# ─── 1. Cargar JSON existente ─────────────────────────────────────────────────

def load_db():
    if os.path.exists(JSON_PATH):
        with open(JSON_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_db(db):
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

# ─── 2. Pedir películas a Claude ──────────────────────────────────────────────

def ask_claude_for_movies(target_date: str, already_used: list[str]) -> list[dict]:
    """
    Pide a Claude 5 películas variadas para la fecha dada.
    already_used: lista de títulos ya usados para evitar repetición.
    """
    used_str = ", ".join(already_used[-60:]) if already_used else "ninguna todavía"

    prompt = f"""Eres el curador de un juego diario de cine tipo Wordle llamado CineFrame.
Para la fecha {target_date} necesito exactamente 5 películas.

Reglas:
- Mezcla épocas: al menos una anterior a 1980, una entre 1980-2000, una posterior a 2000.
- Mezcla nacionalidades: máximo 2 americanas. Incluye al menos 2 de países no anglosajones.
- Variedad de géneros: drama, thriller, comedia, ciencia ficción, etc.
- Dificultad progresiva: la primera película relativamente conocida, la quinta más oscura.
- NO repitas ninguna de estas películas ya usadas: {used_str}
- Las películas deben ser reales y verificables en Wikipedia en español.

Responde ÚNICAMENTE con un array JSON válido, sin texto adicional, sin markdown, sin comentarios.
Formato exacto:
[
  {{
    "title": "Título original en español o el más conocido",
    "title_en": "Original English title or native title",
    "year": 1994,
    "nationality": "Americana",
    "director": "Nombre del director",
    "hint": "Una pista breve sin revelar el título (máx 4 palabras)"
  }},
  ...
]

Nacionalidades válidas: {", ".join(NATIONALITIES)}
"""

    body = json.dumps({
        "model": "claude-sonnet-4-6",
        "max_tokens": 1000,
        "messages": [{"role": "user", "content": prompt}]
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={
            "Content-Type": "application/json",
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01"
        },
        method="POST"
    )

    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read())

    raw = data["content"][0]["text"].strip()
    # Limpiar posibles ```json ... ```
    raw = re.sub(r"^```[a-z]*\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw)
    return json.loads(raw)

# ─── 3. Buscar imagen en Wikipedia ───────────────────────────────────────────

WIKI_HEADERS = {
    "User-Agent": "CineFrameBot/1.0 (educational game; contact via GitHub)"
}

def wiki_api(params: dict) -> dict:
    base = "https://es.wikipedia.org/w/api.php"
    params["format"] = "json"
    url = base + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=WIKI_HEADERS)
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())

def get_movie_image(title: str, title_en: str, year: int) -> str | None:
    """
    Busca la imagen principal del artículo de Wikipedia de la película.
    Intenta primero en español, luego en inglés.
    """
    candidates = [
        f"{title} (película {year})",
        f"{title} (película)",
        title,
        f"{title_en} (film)",
        f"{title_en} ({year} film)",
        title_en,
    ]

    for candidate in candidates:
        image_url = _try_wiki_page_image(candidate, lang="es")
        if image_url:
            return image_url

    # Fallback: Wikipedia en inglés
    for candidate in [f"{title_en} (film)", f"{title_en} ({year} film)", title_en]:
        image_url = _try_wiki_page_image(candidate, lang="en")
        if image_url:
            return image_url

    return None

def _try_wiki_page_image(page_title: str, lang: str = "es") -> str | None:
    base = f"https://{lang}.wikipedia.org/w/api.php"
    params = {
        "action": "query",
        "titles": page_title,
        "prop": "pageimages",
        "pithumbsize": 1280,
        "format": "json"
    }
    url = base + "?" + urllib.parse.urlencode(params)
    try:
        req = urllib.request.Request(url, headers=WIKI_HEADERS)
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        pages = data.get("query", {}).get("pages", {})
        for page in pages.values():
            if page.get("pageid", -1) < 0:
                continue
            thumb = page.get("thumbnail", {}).get("source")
            if thumb:
                # Ampliar resolución: reemplazar /320px- por /1280px-
                thumb = re.sub(r"/\d+px-", "/1280px-", thumb)
                return thumb
    except Exception:
        pass
    return None

def _search_wiki_image(query: str, lang: str = "es") -> str | None:
    """Búsqueda libre en Wikipedia si no encuentra la página exacta."""
    base = f"https://{lang}.wikipedia.org/w/api.php"
    params = {
        "action": "query",
        "list": "search",
        "srsearch": query,
        "srlimit": 3,
        "format": "json"
    }
    url = base + "?" + urllib.parse.urlencode(params)
    try:
        req = urllib.request.Request(url, headers=WIKI_HEADERS)
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        results = data.get("query", {}).get("search", [])
        for result in results:
            img = _try_wiki_page_image(result["title"], lang)
            if img:
                return img
    except Exception:
        pass
    return None

# ─── 4. Imagen de respaldo con póster ─────────────────────────────────────────

FALLBACK_IMAGE = "https://upload.wikimedia.org/wikipedia/commons/thumb/a/ac/No_image_available.svg/1280px-No_image_available.svg.png"

def get_best_image(movie: dict) -> str:
    print(f"  🔍 Buscando imagen para: {movie['title']} ({movie['year']})")
    img = get_movie_image(movie["title"], movie["title_en"], movie["year"])
    if img:
        print(f"  ✅ Imagen encontrada: {img[:70]}...")
        return img
    # Último intento: búsqueda libre
    for query in [f"{movie['title_en']} film poster", f"{movie['title']} película"]:
        img = _search_wiki_image(query, "en")
        if img:
            print(f"  ✅ Imagen por búsqueda: {img[:70]}...")
            return img
    print(f"  ⚠️  Sin imagen, usando placeholder")
    return FALLBACK_IMAGE

# ─── 5. Main ──────────────────────────────────────────────────────────────────

def main():
    # Fecha objetivo: mañana
    tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()

    # Si se pasa un argumento, usar esa fecha (para pruebas: python generate.py 2025-06-21)
    if len(sys.argv) > 1:
        tomorrow = sys.argv[1]

    print(f"\n🎬 CineFrame — generando películas para {tomorrow}\n")

    db = load_db()

    # Comprobar si ya existe esa fecha
    if any(entry["date"] == tomorrow for entry in db):
        print(f"⚠️  Ya existe una entrada para {tomorrow}. Saliendo.")
        return

    # Títulos ya usados para evitar repetición
    already_used = [m["title"] for entry in db for m in entry["movies"]]

    # Pedir películas a Claude
    print("🤖 Pidiendo películas a Claude...")
    movies_raw = ask_claude_for_movies(tomorrow, already_used)
    print(f"✅ Claude sugirió {len(movies_raw)} películas\n")

    # Buscar imágenes
    movies_final = []
    for m in movies_raw:
        image = get_best_image(m)
        movies_final.append({
            "title": m["title"],
            "year": m["year"],
            "nationality": m["nationality"],
            "director": m.get("director", ""),
            "hint": m.get("hint", ""),
            "image": image
        })
        print()

    # Guardar en JSON
    db.append({
        "date": tomorrow,
        "movies": movies_final
    })

    # Mantener solo los últimos 60 días para no crecer indefinidamente
    db = sorted(db, key=lambda e: e["date"])[-60:]

    save_db(db)
    print(f"💾 peliculas.json actualizado con {len(movies_final)} películas para {tomorrow}")
    print("\nPelículas del día:")
    for i, m in enumerate(movies_final, 1):
        print(f"  {i}. {m['title']} ({m['year']}) — {m['nationality']}")

if __name__ == "__main__":
    main()
