import os, json, re, time, html, requests, feedparser

WEBHOOK = os.environ["DISCORD_WEBHOOK"]
SEEN_FILE = "seen.json"
USER_AGENT = "Mozilla/5.0 (compatible; WorldNewsBot/1.0)"


def icon(domain):
    return f"https://www.google.com/s2/favicons?domain={domain}&sz=128"


def google_news(site):
    return f"https://news.google.com/rss/search?q=when:24h+site:{site}&hl=en-US&gl=US&ceid=US:en"


# Para quitar un medio, borra su bloque. Para añadir uno, copia un bloque y cambia los datos.
# "color": color de la barra lateral de la tarjeta (formato 0xRRGGBB).
# "skip_filter": True -> publica todo el feed sin filtrar por palabras clave.
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
    # --- Ciencia y tecnología (sin filtro, todo el contenido es del tema) ---
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
        "skip_filter": True,
    },
    # EXPERIMENTALES (vía Google News):
    "Associated Press": {
        "url": google_news("apnews.com"),
        "domain": "apnews.com",
        "color": 0xFF6F00,
        "google_news": True,
    },
    "Asahi Shimbun": {
        "url": google_news("asahi.com/ajw"),
        "domain": "asahi.com",
        "color": 0x9C27B0,
        "google_news": True,
    },
}

# Solo se publican noticias cuyo titular o resumen contenga alguna de estas palabras
# (excepto los feeds marcados con "skip_filter").
KEYWORDS = re.compile(
    # Ucrania y Rusia
    r"ukrain|russia|putin|zelensk|kremlin|\bnato\b|"
    # Oriente Medio y África
    r"\biran|israel|gaza|hamas|hezbollah|houthi|lebanon|syria|yemen|sudan|middle east|"
    # Asia
    r"china|taiwan|korea|"
    # EEUU: personas y cargos
    r"\btrump\b|\bvance\b|\brubio\b|\bhegseth\b|\bbessent\b|"
    # EEUU: instituciones y política
    r"white house|oval office|pentagon|state department|treasury|federal reserve|"
    r"congress|senate|\bsenator|house of representatives|\bspeaker\b|supreme court|"
    r"republican|democrat|\bGOP\b|midterm|\bCIA\b|national security|"
    r"tariff|trade war|government shutdown|"
    # Europa
    r"european union|\bEU\b|brussels|macron|merz|starmer|"
    # Conflicto y diplomacia general
    r"election|sanction|ceasefire|cease-fire|\bwar\b|missile|drone|nuclear|"
    r"genocide|peace talks|summit|\bcoup\b|"
    # Ciencia y física
    r"scientist|\bscience\b|scientific|physics|physicist|quantum|particle|\bcern\b|"
    r"astronom|astrophys|telescope|\bnobel\b|genom|\bDNA\b|crispr|biotech|"
    r"nuclear fusion|fusion reactor|climate|\bvaccine|"
    # Espacio
    r"\bnasa\b|\besa\b|spacex|blue origin|rocket|satellite|spacecraft|astronaut|"
    r"asteroid|outer space|space station|\bmoon\b|\bmars\b|\bISS\b|"
    # Tecnología e inteligencia artificial
    r"artificial intelligence|\bAI\b|chatbot|chatgpt|openai|anthropic|nvidia|"
    r"semiconductor|microchip|\bGPU\b|machine learning|\bLLM\b|robot|supercomputer|"
    r"cyberattack|cybersecurity|ransomware|\bhackers?\b|data breach|spyware|encryption|"
    r"big tech|tech giant|\btech\b|technology|elon musk|\bgoogle\b|\bmicrosoft\b|\btesla\b",
    re.IGNORECASE,
)

MAX_PER_RUN = 1  # PRUEBA: súbelo a 25 cuando termines de probar
SUMMARY_LIMIT = 220  # caracteres máximos del resumen


def load_seen():
    try:
        with open(SEEN_FILE) as f:
            return set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def clean(text, limit=SUMMARY_LIMIT):
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(re.sub(r"\s+", " ", text)).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + "…"


def get_image(e):
    for key in ("media_thumbnail", "media_content"):
        items = e.get(key)
        if items and items[0].get("url"):
            return items[0]["url"]
    for link in e.get("links", []):
        if link.get("type", "").startswith("image") and link.get("href"):
            return link["href"]
    return None


def get_title(cfg, e):
    title = (e.get("title") or "").strip()
    # Google News añade " - Nombre del medio" al final del titular
    if cfg.get("google_news") and " - " in title:
        title = title.rsplit(" - ", 1)[0]
    return title


def build_embed(cfg, e):
    embed = {
        "title": get_title(cfg, e)[:250],
        "url": e.get("link", ""),
        "color": cfg["color"],
    }
    if not cfg.get("google_news"):
        desc = clean(e.get("summary", ""))
        if desc:
            embed["description"] = desc
        img = get_image(e)
        if img:
            embed["thumbnail"] = {"url": img}
    if e.get("published_parsed"):
        embed["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", e["published_parsed"])
    return embed


def post(source, cfg, embed):
    payload = {
        "username": source,
        "avatar_url": icon(cfg["domain"]),
        "embeds": [embed],
    }
    for _ in range(3):
        r = requests.post(WEBHOOK, json=payload)
        if r.status_code == 429:
            time.sleep(float(r.json().get("retry_after", 2)) + 0.5)
            continue
        if r.status_code >= 400:
            print(f"Error Discord {r.status_code}:
