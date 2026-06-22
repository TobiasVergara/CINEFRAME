#!/usr/bin/env python3
import os
import json
import datetime
import urllib.request
import urllib.error
import urllib.parse
import re
import sys
import time

GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
if not GOOGLE_API_KEY:
    raise ValueError("No se encontro GOOGLE_API_KEY ni GEMINI_API_KEY")

JSON_PATH = os.path.join(os.path.dirname(__file__), "peliculas.json")

NATIONALITIES = [
    "Americana", "Espanola", "Francesa", "Italiana", "Britanica",
    "Alemana", "Japonesa", "Coreana", "Mexicana", "Argentina",
    "Sueca", "Danesa", "Rusa", "China", "Irani",
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

def call_gemini(prompt):
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.9, "maxOutputTokens": 1000}
    }).encode("utf-8")

    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-lite:generateContent?key=" + GOOGLE_API_KEY

    max_retries = 5
    wait = 60
    for attempt in range(1, max_retries + 1):
        print(f"  Intento {attempt}/{max_retries}...")
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            body_err = e.read().decode()
            print(f"  HTTP {e.code}: {body_err[:300]}")
            if e.code == 429 and attempt < max_retries:
                print(f"  Esperando {wait}s...")
                time.sleep(wait)
                wait = min(wait * 2, 300)
            else:
                raise
    raise RuntimeError("Maximos reintentos alcanzados")

def ask_gemini_for_movies(target_date, already_used):
    used_str = ", ".join(already_used[-60:]) if already_used else "ninguna"
    prompt = (
        "Eres el curador de un juego diario de cine tipo Wordle llamado CineFrame.\n"
        f"Para la fecha {target_date} necesito exactamente 5 peliculas.\n\n"
        "Reglas:\n"
        "- Mezcla epocas: al menos una anterior a 1980, una entre 1980-2000, una posterior a 2000.\n"
        "- Mezcla nacionalidades: maximo 2 americanas. Incluye al menos 2 no anglosajonas.\n"
        "- Variedad de generos.\n"
        "- Dificultad progresiva: la primera conocida, la quinta mas oscura.\n"
        f"- NO repitas: {used_str}\n\n"
        "Responde UNICAMENTE con un array JSON, sin markdown ni comentarios.\n"
        "Formato:\n"
        '[{"title":"Titulo","title_en":"English title","year":1994,"nationality":"Americana","director":"Director","hint":"pista corta"}]\n\n'
        f"Nacionalidades validas: {', '.join(NATIONALITIES)}"
    )
    data = call_gemini(prompt)
    raw = data["candidates"][0]["content"]["parts"][0]["text"].strip()
    raw = re.sub(r"^```[a-z]*\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw)
    return json.loads(raw)

WIKI_HEADERS = {"User-Agent": "CineFrameBot/1.0 (github)"}

def _try_wiki_image(page_title, lang="es"):
    params = {"action": "query", "titles": page_title, "prop": "pageimages", "pithumbsize": 1280, "format": "json"}
    url = f"https://{lang}.wikipedia.org/w/api.php?" + urllib.parse.urlencode(params)
    try:
        req = urllib.request.Request(url, headers=WIKI_HEADERS)
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        for page in data.get("query", {}).get("pages", {}).values():
            if page.get("pageid", -1) < 0:
                continue
            thumb = page.get("thumbnail", {}).get("source")
            if thumb:
                return re.sub(r"/\d+px-", "/1280px-", thumb)
    except Exception:
        pass
    return None

def _search_wiki_image(query, lang="en"):
    params = {"action": "query", "list": "search", "srsearch": query, "srlimit": 3, "format": "json"}
    url = f"https://{lang}.wikipedia.org/w/api.php?" + urllib.parse.urlencode(params)
    try:
        req = urllib.request.Request(url, headers=WIKI_HEADERS)
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        for result in data.get("query", {}).get("search", []):
            img = _try_wiki_image(result["title"], lang)
            if img:
                return img
    except Exception:
        pass
    return None

FALLBACK = "https://upload.wikimedia.org/wikipedia/commons/thumb/a/ac/No_image_available.svg/1280px-No_image_available.svg.png"

def get_best_image(movie):
    print(f"  Imagen: {movie['title']} ({movie['year']})")
    for candidate, lang in [
        (f"{movie['title']} (pelicula {movie['year']})", "es"),
        (f"{movie['title']} (pelicula)", "es"),
        (movie["title"], "es"),
        (f"{movie['title_en']} ({movie['year']} film)", "en"),
        (f"{movie['title_en']} (film)", "en"),
        (movie["title_en"], "en"),
    ]:
        img = _try_wiki_image(candidate, lang)
        if img:
            print(f"  OK: {img[:70]}...")
            return img
    img = _search_wiki_image(f"{movie['title_en']} film", "en")
    if img:
        print(f"  OK (busqueda): {img[:70]}...")
        return img
    print("  Usando placeholder")
    return FALLBACK

def main():
    tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
    if len(sys.argv) > 1:
        tomorrow = sys.argv[1]

    print(f"\nCineFrame -- generando peliculas para {tomorrow}\n")
    db = load_db()

    if any(e["date"] == tomorrow for e in db):
        print(f"Ya existe {tomorrow}. Saliendo.")
        return

    already_used = [m["title"] for e in db for m in e["movies"]]

    print("Llamando a Gemini...")
    movies_raw = ask_gemini_for_movies(tomorrow, already_used)
    print(f"Gemini devolvio {len(movies_raw)} peliculas\n")

    movies_final = []
    for m in movies_raw:
        img = get_best_image(m)
        movies_final.append({
            "title": m["title"],
            "year": m["year"],
            "nationality": m["nationality"],
            "director": m.get("director", ""),
            "hint": m.get("hint", ""),
            "image": img
        })
        print()

    db.append({"date": tomorrow, "movies": movies_final})
    db = sorted(db, key=lambda e: e["date"])[-60:]
    save_db(db)

    print(f"peliculas.json actualizado para {tomorrow}")
    for i, m in enumerate(movies_final, 1):
        print(f"  {i}. {m['title']} ({m['year']}) -- {m['nationality']}")

if __name__ == "__main__":
    main()
