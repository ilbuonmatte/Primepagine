from flask import Flask, Response, render_template
import requests
import re
import time

app = Flask(__name__)

# Pagine sorgente (una per giornale) e cache in memoria
FONTI = {
    "libero": "https://thefrontpager.com/it/libero-quotidiano/",
    "laverita": "https://thefrontpager.com/it/la-verita/",
    "repubblica": "https://thefrontpager.com/it/repubblica/",
    "corriere": "https://thefrontpager.com/it/corriere-della-sera/",
    "ilgiornale": "https://thefrontpager.com/it/il-giornale/",
    "manifesto": "https://thefrontpager.com/it/manifesto/",
    "avvenire": "https://thefrontpager.com/it/avvenire/",
    "fattoquotidiano": "https://thefrontpager.com/it/il-fatto-quotidiano/",
    "stampa": "https://thefrontpager.com/it/stampa/",
    "domani": "https://thefrontpager.com/it/domani/",
    "sole24ore": "https://thefrontpager.com/it/il-sole-24-ore/",
}

NOMI = {
    "libero": "Libero",
    "laverita": "La Verità",
    "repubblica": "La Repubblica",
    "corriere": "Corriere della Sera",
    "ilgiornale": "Il Giornale",
    "manifesto": "Il Manifesto",
    "avvenire": "Avvenire",
    "fattoquotidiano": "Il Fatto Quotidiano",
    "stampa": "La Stampa",
    "domani": "Domani",
    "sole24ore": "Il Sole 24 Ore",
}

_cache = {}  # es: {"libero": {"bytes": ..., "content_type": ..., "ts": 12345}}
DURATA_CACHE = 60 * 60  # 1 ora, poi ricontrolla se c'è una nuova immagine

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}


def trova_url_immagine(pagina_url: str) -> str:
    """Scarica la pagina HTML e ne estrae l'immagine (og:image o twitter:image),
    gestendo diversi ordini di attributi e tipi di virgolette."""
    r = requests.get(pagina_url, headers=HEADERS, timeout=15)
    r.raise_for_status()
    html = r.text

    pattern_generico = (
        r'<meta[^>]+(?:property|name)=["\'](?:og:image|twitter:image)["\']'
        r'[^>]+content=["\']([^"\']+)["\']'
    )
    match = re.search(pattern_generico, html, re.IGNORECASE)
    if not match:
        pattern_invertito = (
            r'<meta[^>]+content=["\']([^"\']+)["\']'
            r'[^>]+(?:property|name)=["\'](?:og:image|twitter:image)["\']'
        )
        match = re.search(pattern_invertito, html, re.IGNORECASE)

    if not match:
        raise ValueError(f"Immagine non trovata nella pagina ({pagina_url})")
    return match.group(1)


def scarica_immagine(nome: str):
    """Ritorna (bytes, content_type) usando la cache se ancora valida."""
    ora = time.time()
    voce = _cache.get(nome)
    if voce and (ora - voce["ts"] < DURATA_CACHE):
        return voce["bytes"], voce["content_type"]

    url_immagine = trova_url_immagine(FONTI[nome])
    resp = requests.get(url_immagine, headers=HEADERS, timeout=10)
    resp.raise_for_status()

    _cache[nome] = {
        "bytes": resp.content,
        "content_type": resp.headers.get("Content-Type", "image/jpeg"),
        "ts": ora,
    }
    return resp.content, resp.headers.get("Content-Type", "image/jpeg")


@app.route("/")
def home():
    return render_template("index.html", giornali=NOMI)


@app.route("/debug")
def debug():
    risultati = {}
    for nome, url in FONTI.items():
        try:
            url_immagine = trova_url_immagine(url)
            risultati[nome] = {"ok": True, "url_immagine": url_immagine}
        except Exception as e:
            risultati[nome] = {"ok": False, "errore": str(e)}
    return risultati


@app.route("/img/<nome>")
def img(nome):
    if nome not in FONTI:
        return "Giornale non trovato", 404
    try:
        dati, content_type = scarica_immagine(nome)
        return Response(dati, mimetype=content_type)
    except Exception as e:
        return f"Errore nel recupero immagine: {e}", 502


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
