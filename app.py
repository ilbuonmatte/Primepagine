from flask import Flask, Response, render_template, jsonify
import requests
import re
import time
import hashlib
from datetime import datetime

app = Flask(__name__)

FONTI = {
    "libero": "https://www.giornalone.it/prima-pagina-libero/",
    "laverita": "https://www.giornalone.it/prima-pagina-la-verita/",
    "repubblica": "https://www.giornalone.it/prima-pagina-la-repubblica/",
    "corriere": "https://www.giornalone.it/prima-pagina-corriere-della-sera/",
    "ilgiornale": "https://www.giornalone.it/prima-pagina-il-giornale/",
    "manifesto": "https://www.giornalone.it/prima-pagina-il-manifesto/",
    "avvenire": "https://www.giornalone.it/prima-pagina-avvenire/",
    "fattoquotidiano": "https://www.giornalone.it/prima-pagina-il-fatto-quotidiano/",
    "stampa": "https://www.giornalone.it/prima-pagina-la-stampa/",
    "domani": "https://www.giornalone.it/prima-pagina-domani/",
    "sole24ore": "https://www.giornalone.it/prima-pagina-il-sole-24-ore/",
    "quotidianolecce": "https://www.giornalone.it/prima-pagina-quotidiano-di-puglia/",
    "gazzettamezzogiorno": "https://www.giornalone.it/prima-pagina-la-gazzetta-del-mezzogiorno/",
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
    "quotidianolecce": "Nuovo Quotidiano di Puglia (Lecce)",
    "gazzettamezzogiorno": "La Gazzetta del Mezzogiorno",
}

_cache = {}
_ultimo_cambio = {}
DURATA_CACHE = 60 * 60
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


def trova_url_immagine(pagina_url: str) -> str:
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
    ora = time.time()
    voce = _cache.get(nome)
    if voce and (ora - voce["ts"] < DURATA_CACHE):
        return voce["bytes"], voce["content_type"]

    url_immagine = trova_url_immagine(FONTI[nome])
    resp = requests.get(url_immagine, headers=HEADERS, timeout=10)
    resp.raise_for_status()

    nuovo_hash = hashlib.sha256(resp.content).hexdigest()
    hash_precedente = voce["hash"] if voce else None

    if nuovo_hash != hash_precedente:
        _ultimo_cambio[nome] = ora
    elif nome not in _ultimo_cambio:
        _ultimo_cambio[nome] = ora

    _cache[nome] = {
        "bytes": resp.content,
        "content_type": resp.headers.get("Content-Type", "image/jpeg"),
        "ts": ora,
        "hash": nuovo_hash,
    }
    return resp.content, resp.headers.get("Content-Type", "image/jpeg")


@app.route("/")
def home():
    return render_template("index.html", giornali=NOMI)


@app.route("/aggiornamenti")
def aggiornamenti():
    risultato = {}
    for nome in FONTI:
        try:
            scarica_immagine(nome)
        except Exception:
            pass
        ts = _ultimo_cambio.get(nome)
        if ts:
            risultato[nome] = datetime.fromtimestamp(ts).strftime("%d/%m/%Y")
        else:
            risultato[nome] = None
    return jsonify(risultato)


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
