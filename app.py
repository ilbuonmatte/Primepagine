from flask import Flask, Response, render_template, jsonify, request, redirect, url_for, session
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import requests
import re
import time
import hashlib
import json
import os
from datetime import datetime
import firebase_admin
from firebase_admin import credentials, firestore

# --- Connessione a Firebase (stesso progetto usato per Fantaprof) ---
_cred_json = os.environ.get("FIREBASE_CREDENTIALS")
if _cred_json:
    _cred = credentials.Certificate(json.loads(_cred_json))
    firebase_admin.initialize_app(_cred)
    db = firestore.client()
else:
    db = None  # senza credenziali il sito parte comunque, ma il login utenti extra non funziona

COLLEZIONE_UTENTI = "utenti_primepagine"  # collezione dedicata, separata da quelle di Fantaprof

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "cambia-questa-chiave-su-render")

# --- Credenziali amministratore (le imposti tu su Render, vedi istruzioni) ---
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "cambiami123")

def carica_utenti():
    if not db:
        return {}
    utenti = {}
    for doc in db.collection(COLLEZIONE_UTENTI).stream():
        utenti[doc.id] = doc.to_dict()
    return utenti


def crea_utente(username, password):
    if db:
        db.collection(COLLEZIONE_UTENTI).document(username).set(
            {"password_hash": generate_password_hash(password)}
        )


def elimina_utente(username):
    if db:
        db.collection(COLLEZIONE_UTENTI).document(username).delete()


def richiedi_login(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("utente"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


def richiedi_admin(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if session.get("utente") != ADMIN_USER:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


@app.route("/login", methods=["GET", "POST"])
def login():
    errore = None
    if request.method == "POST":
        u = request.form.get("username", "").strip()
        p = request.form.get("password", "")

        if u == ADMIN_USER and p == ADMIN_PASSWORD:
            session["utente"] = ADMIN_USER
            return redirect(url_for("home"))

        utenti = carica_utenti()
        if u in utenti and check_password_hash(utenti[u]["password_hash"], p):
            session["utente"] = u
            return redirect(url_for("home"))

        errore = "Username o password non corretti."
    return render_template("login.html", errore=errore)


@app.route("/logout")
def logout():
    session.pop("utente", None)
    return redirect(url_for("login"))


@app.route("/admin", methods=["GET", "POST"])
@richiedi_admin
def admin():
    messaggio = None
    if not db:
        messaggio = "⚠️ Firebase non è collegato: imposta FIREBASE_CREDENTIALS su Render."

    if request.method == "POST":
        azione = request.form.get("azione")

        if azione == "aggiungi":
            nuovo_user = request.form.get("nuovo_username", "").strip()
            nuova_pass = request.form.get("nuova_password", "")
            if nuovo_user and nuova_pass:
                crea_utente(nuovo_user, nuova_pass)
                messaggio = f"Utente '{nuovo_user}' creato."

        elif azione == "elimina":
            da_eliminare = request.form.get("username")
            if da_eliminare:
                elimina_utente(da_eliminare)
                messaggio = f"Utente '{da_eliminare}' eliminato."

    utenti = carica_utenti()
    return render_template("admin.html", utenti=utenti, messaggio=messaggio)

# Pagine sorgente (una per giornale) e cache in memoria
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

_cache = {}  # es: {"libero": {"bytes": ..., "content_type": ..., "ts": 12345, "hash": "..."}}
_ultimo_cambio = {}  # es: {"libero": timestamp dell'ultima volta che l'immagine è REALMENTE cambiata}
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
    """Ritorna (bytes, content_type) usando la cache se ancora valida.
    Aggiorna _ultimo_cambio SOLO quando l'immagine scaricata è diversa dalla precedente."""
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
        _ultimo_cambio[nome] = ora  # l'immagine è davvero cambiata: aggiorna la data
    elif nome not in _ultimo_cambio:
        _ultimo_cambio[nome] = ora  # prima volta in assoluto

    _cache[nome] = {
        "bytes": resp.content,
        "content_type": resp.headers.get("Content-Type", "image/jpeg"),
        "ts": ora,
        "hash": nuovo_hash,
    }
    return resp.content, resp.headers.get("Content-Type", "image/jpeg")


@app.route("/")
@richiedi_login
def home():
    return render_template("index.html", giornali=NOMI, utente=session.get("utente"))


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


@app.route("/aggiornamenti")
@richiedi_login
def aggiornamenti():
    """Ritorna, per ogni giornale, la data dell'ultima volta che l'immagine è REALMENTE cambiata."""
    risultato = {}
    for nome in FONTI:
        try:
            scarica_immagine(nome)  # assicura che la cache/hash siano aggiornati
        except Exception:
            pass
        ts = _ultimo_cambio.get(nome)
        if ts:
            risultato[nome] = datetime.fromtimestamp(ts).strftime("%d/%m/%Y")
        else:
            risultato[nome] = None
    return jsonify(risultato)


@app.route("/img/<nome>")
@richiedi_login
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
