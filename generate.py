#!/usr/bin/env python3
"""
CineFrame — Daily movie generator (Gemini version, free tier)
"""

import os
import json
import datetime
import urllib.request
import urllib.parse
import re
import sys

GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
JSON_PATH = os.path.join(os.path.dirname(__file__), "peliculas.json")

NATIONALITIES = [
    "Americana", "Española", "Francesa", "Italiana", "Británica",
    "Alemana", "Japonesa", "Coreana", "Mexicana", "Argentina",
    "Sueca", "Danesa", "Rusa / Soviética", "China", "Iraní",
    "India", "Australiana", "Canadiense", "Belga", "Polaca"
]

def load_db():
    if os.path.exists(JSON_PATH):
        with open(JSON_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_db(db):
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

def ask_gemini_for_movies(target_date, already_used):
    used_str = ", ".join(already_used[-60:]) if already_used else "ninguna todavía"

    prompt = f"""Eres el curador de un juego diario de cine tipo Wordle llamado CineFrame.
Para la fecha {target_date} necesito exactamente 5 películas.

Reglas:
- Mezcla épocas: al menos una anterior a 1980, una entre 1980-2000, una posterior a 2000.
- Mezcla nacionalidades: máximo 2 americanas. Incluye al menos 2 de países no anglosajones.
- Variedad de géneros: drama, thriller, comedia, ciencia ficción, etc.
- Dificultad progresiva: la primera relativamente conocida, la quinta más oscura.
- NO repitas ninguna de estas películas ya usadas: {used_str}
- Las películas deben ser reales y verificables en Wikipedia en español.

Responde ÚNICAMENTE con un array JSON válido, sin texto adicional, sin markdown, sin comentarios.
Formato exacto:
[
  {{
    "title": "Título en español o el más conocido",
    "title_en": "Título original en inglés o idioma nativo",
    "year": 1994,
    "nationality": "Americana",
    "director": "Nombre del director",
    "hint": "Una pista breve sin revelar el título (máx 4 palabras)"
  }}
]

Nacionalidades válidas: {", ".join(NATIONALITIES)}"""

    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.9, "maxOutputTokens": 1000}
    }).encode("utf-8")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GOOGLE_API_KEY}"
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")

    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        error_body = e.read().decode()
        print("Error de Gemini:", error_body)
        raise

    raw = data["candidates"][0]["content"]["parts"][0]["text"].strip()
    raw = re.sub(r"^```[a-z]*\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw)
    return json.loads(raw)

WIKI_HEADERS = {"User-Agent": "CineFrameBot/1.0 (educational game; contact via GitHub)"}

def _try_wiki_page_image(page_title, lang="es"):
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
                thumb = re.sub(r"/\d+px-", "/1280px-", thumb)
                return thumb
    except Exception:
        pass
    return None

def _search_wiki_image(query, lang="en"):
    base = f"https://{lang}.wikipedia.org/w/api.php"
    params = {"action": "query", "list": "search", "srsearch": query, "srlimit": 3, "format": "json"}
    url = base + "?" + urllib.parse.urlencode(params)
    try:
        req = urllib.request.Request(url, headers=WIKI_HEADERS)
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        for result in data.get("query", {}).get("search", []):
            img = _try_wiki_page_image(result["title"], lang)
            if img:
                return img
    except Exception:
        pass
    return None

FALLBACK_IMAGE = "https://upload.wikimedia.org/wikipedia/commons/thumb/a/ac/No_image_available.svg/1280px-No_image_available.svg.png"

def get_best_image(movie):
    print(f"  🔍 Buscando imagen: {movie['title']} ({movie['year']})")
    candidates_es = [
        f"{movie['title']} (película {movie['year']})",
        f"{movie['title']} (película)",
        movie['title'],
    ]
    candidates_en = [
        f"{movie['title_en']} ({movie['year']} film)",
        f"{movie['title_en']} (film)",
        movie['title_en'],
    ]
    for c in candidates_es:
        img = _try_wiki_page_image(c, "es")
        if img:
            print(f"  ✅ {img[:70]}...")
            return img
    for c in candidates_en:
        img = _try_wiki_page_image(c, "en")
        if img:
            print(f"  ✅ {img[:70]}...")
            return img
    img = _search_wiki_image(f"{movie['title_en']} film", "en")
    if img:
        print(f"  ✅ (búsqueda) {img[:70]}...")
        return img
    print(f"  ⚠️  Sin imagen, usando placeholder")
    return FALLBACK_IMAGE

def main():
    tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
    if len(sys.argv) > 1:
        tomorrow = sys.argv[1]

    print(f"\n🎬 CineFrame — generando películas para {tomorrow}\n")

    db = load_db()

    if any(e["date"] == tomorrow for e in db):
        print(f"⚠️  Ya existe una entrada para {tomorrow}. Saliendo.")
        return

    already_used = [m["title"] for e in db for m in e["movies"]]

    print("🤖 Pidiendo películas a Gemini...")
    movies_raw = ask_gemini_for_movies(tomorrow, already_used)
    print(f"✅ Gemini sugirió {len(movies_raw)} películas\n")

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

    db.append({"date": tomorrow, "movies": movies_final})
    db = sorted(db, key=lambda e: e["date"])[-60:]
    save_db(db)

    print(f"💾 peliculas.json actualizado con {len(movies_final)} películas para {tomorrow}")
    print("\nPelículas del día:")
    for i, m in enumerate(movies_final, 1):
        print(f"  {i}. {m['title']} ({m['year']}) — {m['nationality']}")

if __name__ == "__main__":
    main()

