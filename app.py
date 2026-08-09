from flask import Flask, Response, render_template
import requests
import re
import time

app = Flask(__name__)

# Pagine sorgente (una per giornale) e cache in memoria
FONTI = {
    "libero": "https://www.giornalone.it/prima-pagina-libero/",
    "laverita": "https://www.giornalone.it/prima-pagina-la-verita/",
}

_cache = {}  # es: {"libero": {"bytes": ..., "content_type": ..., "ts": 12345}}
DURATA_CACHE = 3 * 60 * 60  # 3 ore, poi ricontrolla se c'è una nuova immagine

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}


def trova_url_immagine(pagina_url: str) -> str:
    """Scarica la pagina HTML e ne estrae l'immagine og:image (la prima pagina di oggi)."""
    r = requests.get(pagina_url, headers=HEADERS, timeout=10)
    r.raise_for_status()
    match = re.search(r'<meta property="og:image" content="([^"]+)"', r.text)
    if not match:
        raise ValueError("Immagine non trovata nella pagina")
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
    return render_template("index.html")


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
