import os, json, re, time, html, requests, feedparser

WEBHOOK = os.environ["DISCORD_WEBHOOK"]
SEEN_FILE = "seen.json"
RECENT_FILE = "recent.json"
USER_AGENT = "Mozilla/5.0 (compatible; WorldNewsBot/1.0)"

# --- Ajustes anti-duplicados ---
RECENT_HOURS = 48
SIMILARITY_JACCARD = 0.5
SIMILARITY_OVERLAP = 0.75

MAX_PER_RUN = 1  # PRUEBA: súbelo a 25 cuando termines de probar
SUMMARY_LIMIT = 220


def icon(domain):
    base = "https://www.google.com/s2/favicons"
    return f"{base}?domain={domain}&sz=128"


def google_news(site):
    base = "https://news.google.com/rss/search"
    return f"{base}?q=when:24h+site:{site}&hl=en-US&gl=US&ceid=US:en"


# Para quitar un medio, borra su bloque.
# El ORDEN importa: si dos medios publican lo mismo, se queda el primero.
# "color": color de la barra lateral (formato 0xRRGGBB).
# "skip_filter": True -> publica todo sin filtrar por palabras.
FEEDS = {
    # --- Geopolítica y actualidad mundial ---
    "BBC": {
        "url": "https://feeds.bbci.co.uk/news/world/rss.xml",
        "domain": "bbc.com",
        "color": 0xBB1919,
    },
    "The Guardian": {
        "url": "https://www.theguardian.com/world/rss",
        "domain": "theguardian.com",
        "color": 0x1E5AA8,
    },
    "DW": {
        "url": "https://rss.dw.com/xml/rss-en-world",
        "domain": "dw.com",
        "color": 0x00A5FF,
    },
    "Kyiv Independent": {
        "url": "https://kyivindependent.com/news-archive/rss/",
        "domain": "kyivindependent.com",
        "color": 0xFFD500,
    },
    "POLITICO Europe": {
        "url": "https://www.politico.eu/feed/",
        "domain": "politico.eu",
        "color": 0xE0001B,
    },
    "POLITICO US": {
        "url": "https://www.politico.com/rss/politicopicks.xml",
        "domain": "politico.com",
        "color": 0x8E0F1D,
    },
    "Al Jazeera": {
        "url": "https://www.aljazeera.com/xml/rss/all.xml",
        "domain": "aljazeera.com",
        "color": 0xF9A825,
    },
    # --- Ciencia y tecnología (sin filtro) ---
    "BBC Science": {
        "url": "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml",
        "domain": "bbc.com",
        "color": 0x2E7D32,
        "skip_filter": True,
    },
    "BBC Technology": {
        "url": "https://feeds.bbci.co.uk/news/technology/rss.xml",
        "domain": "bbc.com",
        "color": 0x00838F,
        "skip_filter": True,
    },
    "Guardian Science": {
        "url": "https://www.theguardian.com/science/rss",
        "domain": "theguardian.com",
        "color": 0x2E7D32,
        "skip_filter": True,
    },
    "Guardian Technology": {
        "url": "https://www.theguardian.com/technology/rss",
        "domain": "theguardian.com",
        "color": 0x00838F,
        "skip_filter":
