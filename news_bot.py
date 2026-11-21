import os, json, re, time, html, calendar, requests, feedparser
from datetime import datetime
from zoneinfo import ZoneInfo

WEBHOOK = os.environ["DISCORD_WEBHOOK"]
SEEN_FILE = "seen.json"
RECENT_FILE = "recent.json"
USER_AGENT = "Mozilla/5.0 (compatible; WorldNewsBot/1.0)"

# --- Ajustes anti-duplicados ---
RECENT_HOURS = 48
SIMILARITY_JACCARD = 0.5
SIMILARITY_OVERLAP = 0.75

MAX_PER_RUN = 5       # maximo de noticias por ejecucion (total)
MAX_PER_SOURCE = 1    # maximo de noticias de un mismo medio por ejecucion
MAX_AGE_HOURS = 4     # antiguedad maxima normal de una noticia
SUMMARY_LIMIT = 220

# --- Horario de publicacion (hora de Espana, cambia sola en verano/invierno) ---
TIMEZONE = "Europe/Madrid"
FIRST_HOUR = 8        # primera publicacion del dia (08:xx)
LAST_HOUR = 22        # ultima publicacion del dia (22:xx)
MIN_GAP_MINUTES = 110 # tiempo minimo entre publicaciones (~2 horas)
MORNING_MAX_AGE = 11  # la primera del dia recoge noticias de la noche (horas)
LAST_RUN_FILE = "last_run.json"

max_age_hours = MAX_AGE_HOURS


def is_too_old(e):
    published = e.get("published_parsed") or e.get("updated_parsed")
    if not published:
        return False
    age = time.time() - calendar.timegm(published)
    return age > max_age_hours * 3600


def load_last_run():
    try:
        with open(LAST_RUN_FILE) as f:
            return float(json.load(f).get("ts", 0))
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        return 0.0


def should_run():
    """Decide si toca publicar ahora. Devuelve True/False."""
    global max_age_hours
    now_local = datetime.now(ZoneInfo(TIMEZONE))
    manual = os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
    last = load_last_run()
    minutes_since = (time.time() - last) / 60 if last else None

    if not manual:
        if not (FIRST_HOUR <= now_local.hour <= LAST_HOUR):
            print(f"Fuera de horario ({now_local:%H:%M}). No se publica.")
            return False
        if minutes_since is not None and minutes_since < MIN_GAP_MINUTES:
            print(f"Ultima publicacion hace {minutes_since:.0f} min. Se espera.")
            return False

    # Primera del dia (o tras una pausa larga): recoge lo de la noche
    if minutes_since is not None and minutes_since > 5 * 60:
        max_age_hours = MORNING_MAX_AGE
    print(f"Publicando ({now_local:%H:%M} hora local). "
          f"Antiguedad maxima: {max_age_hours} h")
    return True


def icon(domain):
    base = "https://www.google.com/s2/favicons"
    return f"{base}?domain={domain}&sz=128"


def google_news(site):
    base = "https://news.google.com/rss/search"
    return f"{base}?q=when:24h+site:{site}&hl=en-US&gl=US&ceid=US:en"


# Para quitar un medio, borra su bloque.
# El ORDEN importa: si dos medios publican lo mismo, se queda el primero.
# "color": color de la barra lateral (formato 0xRRGGBB).
# "tech_only": True -> solo publica IA, espacio y tecnologia.
FEEDS = {
    # --- Geopolitica y actualidad mundial ---
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
    "Le Monde": {
        "url": "https://www.lemonde.fr/en/international/rss_full.xml",
        "domain": "lemonde.fr",
        "color": 0x5C6BC0,
    },
    "Washington Post": {
        "url": "https://feeds.washingtonpost.com/rss/world",
        "domain": "washingtonpost.com",
        "color": 0xB0BEC5,
    },
    "New York Times": {
        "url": "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
        "domain": "nytimes.com",
        "color": 0xECEFF1,
    },
    "Wall Street Journal": {
        "url": "https://feeds.content.dowjones.io/public/rss/RSSWorldNews",
        "domain": "wsj.com",
        "color": 0x8D6E63,
    },
    "Der Spiegel": {
        "url": "https://www.spiegel.de/international/index.rss",
        "domain": "spiegel.de",
        "color": 0xE64415,
    },
    # --- Ciencia y tecnologia (solo IA, espacio y tecnologia) ---
    "BBC Science": {
        "url": "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml",
        "domain": "bbc.com",
        "color": 0x2E7D32,
        "tech_only": True,
    },
    "BBC Technology": {
        "url": "https://feeds.bbci.co.uk/news/technology/rss.xml",
        "domain": "bbc.com",
        "color": 0x00838F,
        "tech_only": True,
    },
    "Guardian Science": {
        "url": "https://www.theguardian.com/science/rss",
        "domain": "theguardian.com",
        "color": 0x2E7D32,
        "tech_only": True,
    },
    "Guardian Technology": {
        "url": "https://www.theguardian.com/technology/rss",
        "domain": "theguardian.com",
        "color": 0x00838F,
        "tech_only": True,
    },
    # EXPERIMENTALES (via Google News):
    "Reuters": {
        "url": google_news("reuters.com"),
        "domain": "reuters.com",
        "color": 0xFF8000,
        "google_news": True,
    },
    "Asahi Shimbun": {
        "url": google_news("asahi.com/ajw"),
        "domain": "asahi.com",
        "color": 0x9C27B0,
        "google_news": True,
    },
}

# --- Geopolitica y actualidad ---
GEO_PATTERN = (
    # Ucrania y Rusia
    r"ukrain|russia|putin|zelensk|kremlin|\bnato\b|"
    # Oriente Medio y Africa
    r"\biran|israel|gaza|hamas|hezbollah|houthi|lebanon|"
    r"syria|yemen|sudan|middle east|"
    # Asia
    r"china|taiwan|korea|"
    # EEUU: personas y cargos
    r"\btrump\b|\bvance\b|\brubio\b|\bhegseth\b|\bbessent\b|"
    # EEUU: instituciones y politica
    r"white house|oval office|pentagon|state department|"
    r"treasury|federal reserve|congress|senate|\bsenator|"
    r"house of representatives|\bspeaker\b|supreme court|"
    r"republican|democrat|\bGOP\b|midterm|\bCIA\b|"
    r"national security|tariff|trade war|government shutdown|"
    # Europa
    r"european union|\bEU\b|brussels|macron|merz|starmer|"
    # Conflicto y diplomacia general
    r"election|sanction|ceasefire|cease-fire|\bwar\b|missile|"
    r"drone|nuclear|genocide|peace talks|summit|\bcoup\b"
)

# --- IA, exploracion espacial y nuevas tecnologias ---
TECH_PATTERN = (
    # Inteligencia artificial
    r"artificial intelligence|\bAI\b|\bA\.I\.|chatbot|chatgpt|"
    r"openai|anthropic|deepmind|\bgemini\b|\bclaude\b|nvidia|"
    r"machine learning|\bLLMs?\b|neural network|generative|"
    r"deepfake|robot|humanoid|self-driving|driverless|"
    r"autonomous vehicle|"
    # Espacio
    r"\bnasa\b|\besa\b|spacex|starship|blue origin|rocket|"
    r"satellite|spacecraft|space probe|astronaut|cosmonaut|"
    r"space station|\bISS\b|space agency|space exploration|"
    r"outer space|\bmoon\b|lunar|\bmars\b|martian|artemis|"
    r"asteroid|comet|telescope|james webb|exoplanet|galaxy|"
    r"black hole|\borbit|astronom|astrophys|universe|"
    # Nuevas tecnologias
    r"quantum|supercomputer|semiconductor|microchip|\bchips?\b|"
    r"\bGPU\b|nuclear fusion|fusion reactor|\bcern\b|physicist|"
    r"cyberattack|cybersecurity|ransomware|\bhackers?\b|"
    r"data breach|spyware|encryption|big tech|tech giant|"
    r"\btech\b|technology|silicon valley|elon musk|\bgoogle\b|"
    r"\bmicrosoft\b|\btesla\b|smartphone|electric vehicle|"
    r"\b6G\b|virtual reality|augmented reality|brain implant|"
    r"neuralink|3d print"
)

# Temas que NUNCA se publican (se buscan en el titular)
EXCLUDE = re.compile(
    r"animal|\bzoos?\b|wildlife|\bspecies\b|dinosaur|fossil|"
    r"\bbirds?\b|whale|dolphin|shark|\bdogs?\b|\bpupp|\bcats?\b|"
    r"kitten|\bpets?\b|insect|\bbees?\b|butterfl|primate|"
    r"chimpanzee|gorilla|monkey|elephant|\blions?\b|tiger|"
    r"panda|\bbears?\b|penguin|reptile|snake|\bfrogs?\b|"
    r"mammal|creature|\bextinct|predator|\bfish\b|octopus|"
    r"\bhorses?\b|\bcows?\b|\bdeer\b|\bwolf|\bwolves\b|\bfox",
    re.IGNORECASE,
)

# Feeds normales: geopolitica O tecnologia.
KEYWORDS = re.compile(GEO_PATTERN + "|" + TECH_PATTERN, re.IGNORECASE)
# Feeds de ciencia/tecnologia ("tech_only"): solo IA, espacio y tecnologia.
TECH_KEYWORDS = re.compile(TECH_PATTERN, re.IGNORECASE)


STOPWORDS = {
    "a", "an", "the", "of", "in", "on", "at", "to", "for", "and", "or",
    "but", "is", "are", "was", "were", "be", "been", "as", "by", "with",
    "from", "after", "before", "over", "under", "into", "than", "that",
    "this", "these", "those", "it", "its", "says", "say", "said", "new",
    "will", "would", "could", "may", "might", "has", "have", "had", "not",
    "no", "up", "out", "about", "amid", "against", "who", "what", "when",
    "how", "why", "you", "your", "their", "his", "her", "our", "they",
    "them", "just", "more", "most",
}


def load_seen():
    try:
        with open(SEEN_FILE) as f:
            return set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def load_recent():
    try:
        with open(RECENT_FILE) as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    limit = time.time() - RECENT_HOURS * 3600
    return [r for r in data if r.get("ts", 0) >= limit][-300:]


def save_recent(recent):
    with open(RECENT_FILE, "w") as f:
        json.dump(recent[-300:], f)


def tokens(title):
    words = re.findall(r"[a-z0-9]+", title.lower())
    result = set()
    for w in words:
        if w in STOPWORDS or len(w) <= 2:
            continue
        if len(w) > 3 and w.endswith("s"):
            w = w[:-1]
        result.add(w)
    return result


def is_duplicate(tok, others):
    for o in others:
        if not tok or not o:
            continue
        inter = len(tok & o)
        if inter < 3:
            continue
        jaccard = inter / len(tok | o)
        overlap = inter / min(len(tok), len(o))
        if jaccard >= SIMILARITY_JACCARD:
            return True
        if overlap >= SIMILARITY_OVERLAP:
            return True
    return False


def clean(text, limit=SUMMARY_LIMIT):
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(re.sub(r"\s+", " ", text)).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + "..."


def get_image(e):
    for key in ("media_thumbnail", "media_content"):
        items = e.get(key)
        if items and items[0].get("url"):
            return items[0]["url"]
    for link in e.get("links", []):
        if link.get("type", "").startswith("image"):
            if link.get("href"):
                return link["href"]
    return None


OG_PATTERNS = [
    r'<meta[^>]+(?:property|name)=["\'](?:og:image|twitter:image)["\']'
    r'[^>]*content=["\']([^"\']+)["\']',
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]*'
    r'(?:property|name)=["\'](?:og:image|twitter:image)["\']',
]


def fetch_page_image(url):
    # Busca la imagen principal del articulo (og:image) en su pagina web
    if not url:
        return None
    try:
        r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=10)
        if r.status_code >= 400:
            return None
        page = r.text[:300000]
        for pattern in OG_PATTERNS:
            m = re.search(pattern, page, re.IGNORECASE)
            if m:
                img = html.unescape(m.group(1)).strip()
                if img.startswith("//"):
                    img = "https:" + img
                if img.startswith("http"):
                    return img
    except Exception as err:
        print(f"No se pudo leer la imagen de {url}: {err}")
    return None


def get_title(cfg, e):
    title = (e.get("title") or "").strip()
    # Google News anade " - Nombre del medio" al final
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
        img = fetch_page_image(e.get("link", "")) or get_image(e)
        if img:
            embed["image"] = {"url": img}
    if e.get("published_parsed"):
        fmt = "%Y-%m-%dT%H:%M:%SZ"
        embed["timestamp"] = time.strftime(fmt, e["published_parsed"])
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
            wait = float(r.json().get("retry_after", 2)) + 0.5
            time.sleep(wait)
            continue
        if r.status_code >= 400:
            print(f"Error Discord {r.status_code}: {r.text[:200]}")
        return


def main():
    if not should_run():
        return
    seen = load_seen()
    recent = load_recent()
    recent_tokens = [tokens(r["t"]) for r in recent]
    new_items = []

    for source, cfg in FEEDS.items():
        try:
            feed = feedparser.parse(cfg["url"], agent=USER_AGENT)
            print(f"{source}: {len(feed.entries)} entradas")
            entries = feed.entries
            if cfg.get("google_news"):
                entries = sorted(
                    entries,
                    key=lambda x: tuple(x.get("published_parsed") or ()),
                    reverse=True,
                )
            for e in entries[:20]:
                uid = e.get("id") or e.get("link")
                if not uid or uid in seen:
                    continue
                seen.add(uid)
                if is_too_old(e):
                    continue
                if cfg.get("google_news"):
                    # El resumen de Google News trae titulares ajenos
                    text = get_title(cfg, e)
                else:
                    text = f"{get_title(cfg, e)} {e.get('summary', '')}"
                if EXCLUDE.search(get_title(cfg, e)):
                    continue
                if cfg.get("tech_only"):
                    if TECH_KEYWORDS.search(text):
                        new_items.append((source, cfg, e))
                elif KEYWORDS.search(text):
                    new_items.append((source, cfg, e))
        except Exception as err:
            print(f"Error con {source}: {err}")

    print(f"Noticias nuevas relevantes: {len(new_items)}")

    # Reparto por turnos: primero una noticia de cada medio, luego
    # la segunda de cada medio, etc. Asi no acaparan los primeros.
    by_source = {}
    for item in new_items:
        by_source.setdefault(item[0], []).append(item)
    queues = list(by_source.values())
    new_items = []
    while any(queues):
        for q in queues:
            if q:
                new_items.append(q.pop(0))

    posted = 0
    per_source = {}
    for source, cfg, e in new_items:
        if posted >= MAX_PER_RUN:
            break
        if per_source.get(source, 0) >= MAX_PER_SOURCE:
            continue
        title = get_title(cfg, e)
        tok = tokens(title)
        if is_duplicate(tok, recent_tokens):
            print(f"Duplicada ({source}): {title}")
            continue
        post(source, cfg, build_embed(cfg, e))
        recent.append({"t": title, "ts": time.time()})
        recent_tokens.append(tok)
        posted += 1
        per_source[source] = per_source.get(source, 0) + 1
        time.sleep(1.5)

    save_recent(recent)
    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen)[-3000:], f)
    with open(LAST_RUN_FILE, "w") as f:
        json.dump({"ts": time.time()}, f)
    print(f"Terminado correctamente. Publicadas: {posted}")


if __name__ == "__main__":
    main()
