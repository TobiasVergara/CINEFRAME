#!/usr/bin/env python3
"""
CineFrame — Daily movie generator (Gemini + Wikimedia Commons stills)
"""
import os, json, datetime, urllib.request, urllib.error, urllib.parse, re, sys, time

GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
if not GOOGLE_API_KEY:
    raise ValueError("No se encontro GOOGLE_API_KEY ni GEMINI_API_KEY")

JSON_PATH = os.path.join(os.path.dirname(__file__), "peliculas.json")

NATIONALITIES = [
    "Americana","Espanola","Francesa","Italiana","Britanica","Alemana",
    "Japonesa","Coreana","Mexicana","Argentina","Sueca","Danesa",
    "Rusa","China","Irani","India","Australiana","Canadiense","Belga","Polaca","Hungara"
]

def load_db():
    if os.path.exists(JSON_PATH):
        with open(JSON_PATH,"r",encoding="utf-8") as f: return json.load(f)
    return []

def save_db(db):
    with open(JSON_PATH,"w",encoding="utf-8") as f: json.dump(db,f,ensure_ascii=False,indent=2)

def call_gemini(prompt):
    body = json.dumps({
        "contents":[{"parts":[{"text":prompt}]}],
        "generationConfig":{"temperature":0.9,"maxOutputTokens":1200}
    }).encode("utf-8")
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-lite:generateContent?key="+GOOGLE_API_KEY
    max_retries,wait = 6,60
    for attempt in range(1,max_retries+1):
        print(f"  Gemini intento {attempt}/{max_retries}...")
        req = urllib.request.Request(url,data=body,headers={"Content-Type":"application/json"},method="POST")
        try:
            with urllib.request.urlopen(req) as r: return json.loads(r.read())
        except urllib.error.HTTPError as e:
            err = e.read().decode()
            print(f"  HTTP {e.code}: {err[:200]}")
            if e.code==429 and attempt<max_retries:
                print(f"  Esperando {wait}s..."); time.sleep(wait); wait=min(wait*2,300)
            else: raise
    raise RuntimeError("Max reintentos alcanzados")

def ask_gemini_for_movies(target_date, already_used):
    used_str = ", ".join(already_used[-60:]) if already_used else "ninguna"
    prompt = (
        "Eres el curador de CineFrame, un juego diario de cine.\n"
        f"Para {target_date} necesito 5 peliculas con estas reglas:\n"
        "- Mezcla epocas: pre-1980, 1980-2000, post-2000\n"
        "- Max 2 americanas, al menos 2 no anglosajonas\n"
        "- Variedad de generos\n"
        "- Dificultad progresiva (1=conocida, 5=oscura)\n"
        f"- NO repetir: {used_str}\n\n"
        "Responde SOLO con JSON array, sin markdown:\n"
        '[{"title":"titulo es","title_en":"english title","title_original":"titulo original si difiere","year":1994,'
        '"nationality":"Americana","director":"Director","hint":"pista 4 palabras max"}]\n\n'
        f"Nacionalidades: {', '.join(NATIONALITIES)}"
    )
    data = call_gemini(prompt)
    raw = data["candidates"][0]["content"]["parts"][0]["text"].strip()
    raw = re.sub(r"^```[a-z]*\n?","",raw); raw = re.sub(r"\n?```$","",raw)
    return json.loads(raw)

# ── Image search: Wikimedia Commons stills ────────────────────────────────
WIKI_H = {"User-Agent":"CineFrameBot/1.0 (github.com/cineframe)"}

def wikimedia_search_still(movie_title, director, year, lang="en"):
    """Search Wikimedia Commons for actual film stills (not posters)."""
    # Search terms that tend to find stills rather than posters
    queries = [
        f"{movie_title} film still",
        f"{movie_title} screenshot",
        f"{movie_title} {year} scene",
        f"{director} {movie_title}",
    ]
    for q in queries:
        img = _commons_search(q)
        if img:
            return img
    return None

def _commons_search(query):
    """Search Wikimedia Commons for images."""
    params = {
        "action":"query","list":"search","srsearch":query,
        "srnamespace":"6",  # namespace 6 = File
        "srlimit":"5","format":"json"
    }
    url = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(params)
    try:
        req = urllib.request.Request(url,headers=WIKI_H)
        with urllib.request.urlopen(req,timeout=10) as r:
            data = json.loads(r.read())
        results = data.get("query",{}).get("search",[])
        for result in results:
            title = result["title"]
            # Skip posters, covers, logos
            title_lower = title.lower()
            if any(skip in title_lower for skip in ["poster","cover","logo","dvd","blu-ray","artwork","promotional"]):
                continue
            img = _commons_file_url(title)
            if img: return img
    except Exception as e:
        print(f"    Commons search error: {e}")
    return None

def _commons_file_url(file_title):
    """Get direct URL for a Wikimedia Commons file."""
    params = {
        "action":"query","titles":file_title,
        "prop":"imageinfo","iiprop":"url","iiurlwidth":"1280",
        "format":"json"
    }
    url = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(params)
    try:
        req = urllib.request.Request(url,headers=WIKI_H)
        with urllib.request.urlopen(req,timeout=10) as r:
            data = json.loads(r.read())
        pages = data.get("query",{}).get("pages",{})
        for page in pages.values():
            info = page.get("imageinfo",[])
            if info:
                thumb = info[0].get("thumburl") or info[0].get("url")
                if thumb and _is_valid_image(thumb):
                    return thumb
    except Exception:
        pass
    return None

def _is_valid_image(url):
    """Check if URL looks like a real image (not SVG placeholder)."""
    url_lower = url.lower()
    if "no_image" in url_lower or "placeholder" in url_lower: return False
    if url_lower.endswith(".svg"): return False
    return True

def _wiki_page_image(page_title, lang="en"):
    """Fallback: get main image from Wikipedia article."""
    params = {
        "action":"query","titles":page_title,
        "prop":"pageimages","pithumbsize":"1280","format":"json"
    }
    url = f"https://{lang}.wikipedia.org/w/api.php?" + urllib.parse.urlencode(params)
    try:
        req = urllib.request.Request(url,headers=WIKI_H)
        with urllib.request.urlopen(req,timeout=10) as r:
            data = json.loads(r.read())
        for page in data.get("query",{}).get("pages",{}).values():
            if page.get("pageid",-1)<0: continue
            thumb = page.get("thumbnail",{}).get("source")
            if thumb and _is_valid_image(thumb):
                return re.sub(r"/\d+px-","/1280px-",thumb)
    except Exception:
        pass
    return None

FALLBACK = "https://upload.wikimedia.org/wikipedia/commons/thumb/a/ac/No_image_available.svg/1280px-No_image_available.svg.png"

def get_best_image(movie):
    title = movie["title"]
    title_en = movie.get("title_en", title)
    director = movie.get("director","")
    year = movie["year"]
    print(f"  Buscando fotograma: {title} ({year})")

    # 1. Try Wikimedia Commons for actual stills
    img = wikimedia_search_still(title_en, director, year)
    if img: print(f"  OK (commons still): {img[:70]}..."); return img

    img = wikimedia_search_still(title, director, year)
    if img: print(f"  OK (commons still es): {img[:70]}..."); return img

    # 2. Fallback to Wikipedia article image (may be poster, but better than nothing)
    for candidate, lang in [
        (f"{title_en} (film)", "en"),
        (f"{title_en} ({year} film)", "en"),
        (title_en, "en"),
        (f"{title} (pelicula)", "es"),
        (title, "es"),
    ]:
        img = _wiki_page_image(candidate, lang)
        if img: print(f"  OK (wiki fallback): {img[:70]}..."); return img

    print("  Sin imagen, usando placeholder")
    return FALLBACK

def main():
    tomorrow = (datetime.date.today()+datetime.timedelta(days=1)).isoformat()
    if len(sys.argv)>1: tomorrow=sys.argv[1]
    print(f"\nCineFrame -- generando para {tomorrow}\n")

    db = load_db()
    if any(e["date"]==tomorrow for e in db):
        print(f"Ya existe {tomorrow}. Saliendo."); return

    already_used = [m["title"] for e in db for m in e["movies"]]
    print("Llamando a Gemini...")
    movies_raw = ask_gemini_for_movies(tomorrow, already_used)
    print(f"Gemini: {len(movies_raw)} peliculas\n")

    movies_final = []
    for m in movies_raw:
        img = get_best_image(m)
        movies_final.append({
            "title": m["title"],
            "title_en": m.get("title_en",""),
            "title_original": m.get("title_original",""),
            "year": m["year"],
            "nationality": m["nationality"],
            "director": m.get("director",""),
            "hint": m.get("hint",""),
            "image": img
        })
        print()

    db.append({"date":tomorrow,"movies":movies_final})
    db = sorted(db,key=lambda e:e["date"])[-60:]
    save_db(db)
    print(f"Guardado. Peliculas para {tomorrow}:")
    for i,m in enumerate(movies_final,1):
        print(f"  {i}. {m['title']} ({m['year']}) -- {m['nationality']}")

if __name__=="__main__":
    main()
