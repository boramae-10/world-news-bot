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

MAX_PER_RUN = 5       # noticias por tanda (manana / tarde)
MAX_PER_SOURCE = 1    # maximo de noticias de un mismo medio por tanda
SUMMARY_LIMIT = 220

# --- Horario (hora de Espana, cambia sola en verano/invierno) ---
TIMEZONE = "Europe/Madrid"
DIGEST_HOURS = [9, 20]   # tandas: 09:xx (manana) y 20:xx (tarde)
DIGEST_GRACE_HOURS = 3   # si GitHub se retrasa, la tanda aun sale hasta 3 h tarde
DIGEST_MAX_AGE = 14      # la tanda recoge noticias de hasta estas horas
STATE_FILE = "last_run.json"

# --- Breaking news (fuera de las tandas) ---
BREAKING_ENABLED = True
BREAKING_MIN_OUTLETS = 4   # cuantos medios distintos deben cubrir la noticia
BREAKING_WINDOW_HOURS = 3  # ...y todos en las ultimas 3 horas
BREAKING_MAX_PER_DAY = 3   # maximo de breaking news al dia
DAY_FIRST_HOUR = 8         # "de dia" es de 08:00...
DAY_LAST_HOUR = 22         # ...a 22:59
# De noche solo salta si es algo enorme (mas medios a la vez)
BREAKING_NIGHT_ENABLED = True
BREAKING_NIGHT_MIN_OUTLETS = 6

FETCH_PER_FEED = 60        # cuantas entradas se leen de cada feed


def published_ts(e):
    published = e.get("published_parsed") or e.get("updated_parsed")
    if not published:
        return None
    return calendar.timegm(published)


def load_state():
    try:
        with open(STATE_FILE) as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}
    data.setdefault("digests_done", [])
    data.setdefault("breaking_ts", [])
    data.setdefault("last_digest_ts", 0)
    return data


def save_state(state):
    state["digests_done"] = state["digests_done"][-20:]
    cutoff = time.time() - 2 * 86400
    state["breaking_ts"] = [t for t in state["breaking_ts"] if t > cutoff]
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


def due_digest(now_local, state):
    """Devuelve la clave de la tanda que toca ahora, o None."""
    for h in DIGEST_HOURS:
        key = f"{now_local:%Y-%m-%d}@{h}"
        if key in state["digests_done"]:
            continue
        if h <= now_local.hour < h + DIGEST_GRACE_HOURS:
            return key
    return None


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


def post(source, cfg, embed, content=None):
    payload = {
        "username": source,
        "avatar_url": icon(cfg["domain"]),
        "embeds": [embed],
    }
    if content:
        payload["content"] = content
    for _ in range(3):
        r = requests.post(WEBHOOK, json=payload)
        if r.status_code == 429:
            wait = float(r.json().get("retry_after", 2)) + 0.5
            time.sleep(wait)
            continue
        if r.status_code >= 400:
            print(f"Error Discord {r.status_code}: {r.text[:200]}")
        return


def collect_candidates(max_age_hours):
    """Lee todos los feeds y devuelve las noticias que pasan los filtros."""
    now = time.time()
    items = []
    for source, cfg in FEEDS.items():
        try:
            feed = feedparser.parse(cfg["url"], agent=USER_AGENT)
            print(f"{source}: {len(feed.entries)} entradas")
            for e in feed.entries[:FETCH_PER_FEED]:
                ts = published_ts(e)
                if ts is None or now - ts > max_age_hours * 3600:
                    continue
                title = get_title(cfg, e)
                if not title or EXCLUDE.search(title):
                    continue
                if cfg.get("google_news"):
                    # El resumen de Google News trae titulares ajenos
                    text = title
                else:
                    text = f"{title} {e.get('summary', '')}"
                if cfg.get("tech_only"):
                    ok = TECH_KEYWORDS.search(text)
                else:
                    ok = KEYWORDS.search(text)
                if ok:
                    items.append({
                        "source": source, "cfg": cfg, "e": e, "ts": ts,
                        "title": title, "tok": tokens(title),
                    })
        except Exception as err:
            print(f"Error con {source}: {err}")
    return items


def build_stories(items):
    """Agrupa en una 'historia' las noticias de distintos medios sobre lo mismo."""
    stories = []
    for it in items:
        for st in stories:
            if is_duplicate(it["tok"], st["toks"]):
                st["items"].append(it)
                st["toks"].append(it["tok"])
                st["outlets"].add(it["cfg"]["domain"])
                break
        else:
            stories.append({
                "items": [it], "toks": [it["tok"]],
                "outlets": {it["cfg"]["domain"]},
            })
    for st in stories:
        st["first_ts"] = min(i["ts"] for i in st["items"])
        st["last_ts"] = max(i["ts"] for i in st["items"])
    return stories


def publish(item, recent, content=None):
    post(item["source"], item["cfg"], build_embed(item["cfg"], item["e"]), content)
    recent.append({"t": item["title"], "ts": time.time()})
    time.sleep(1.5)


def run_digest(stories, recent):
    """Tanda de manana/tarde: las 5 historias mas cubiertas por los medios."""
    stories.sort(key=lambda s: (len(s["outlets"]), s["last_ts"]), reverse=True)
    posted, used_sources = 0, set()
    for st in stories:
        if posted >= MAX_PER_RUN:
            break
        # Elige el medio que cuenta la historia, evitando repetir medio
        options = [i for i in st["items"] if i["source"] not in used_sources]
        if not options:
            continue
        item = options[0]
        publish(item, recent)
        used_sources.add(item["source"])
        posted += 1
        print(f"Tanda ({len(st['outlets'])} medios): {item['title']}")
    return posted


def run_breaking(stories, recent, state, min_outlets):
    """Breaking news: algo que muchos medios distintos publican a la vez."""
    now = time.time()
    today = [t for t in state["breaking_ts"] if now - t < 86400]
    if len(today) >= BREAKING_MAX_PER_DAY:
        print("Limite diario de breaking news alcanzado.")
        return 0
    candidates = [
        s for s in stories
        if len(s["outlets"]) >= min_outlets
        and now - s["first_ts"] <= BREAKING_WINDOW_HOURS * 3600
    ]
    if not candidates:
        print("Sin breaking news.")
        return 0
    candidates.sort(key=lambda s: len(s["outlets"]), reverse=True)
    st = candidates[0]
    item = st["items"][0]
    publish(item, recent, content="🔴 **BREAKING NEWS**")
    state["breaking_ts"].append(now)
    print(f"BREAKING ({len(st['outlets'])} medios): {item['title']}")
    return 1


def main():
    now_local = datetime.now(ZoneInfo(TIMEZONE))
    manual = os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
    state = load_state()

    digest_key = due_digest(now_local, state)
    is_day = DAY_FIRST_HOUR <= now_local.hour <= DAY_LAST_HOUR
    min_outlets = BREAKING_MIN_OUTLETS if is_day else BREAKING_NIGHT_MIN_OUTLETS
    if manual:
        mode = "tanda"
    elif digest_key:
        mode = "tanda"
    elif BREAKING_ENABLED and (is_day or BREAKING_NIGHT_ENABLED):
        mode = "breaking"
    else:
        print(f"{now_local:%H:%M}: nada que hacer ahora.")
        return
    print(f"{now_local:%H:%M} hora local -> modo: {mode}")

    if mode == "tanda":
        max_age = DIGEST_MAX_AGE
        last = state.get("last_digest_ts", 0)
        if last:
            max_age = min(DIGEST_MAX_AGE, (time.time() - last) / 3600 + 1)
    else:
        max_age = BREAKING_WINDOW_HOURS

    recent = load_recent()
    recent_tokens = [tokens(r["t"]) for r in recent]
    items = collect_candidates(max_age)
    stories = build_stories(items)
    # Quita lo que ya se publico en las ultimas 48 h
    stories = [
        s for s in stories
        if not any(is_duplicate(t, recent_tokens) for t in s["toks"])
    ]
    print(f"Noticias relevantes: {len(items)} | historias nuevas: {len(stories)}")

    if mode == "tanda":
        posted = run_digest(stories, recent)
        if digest_key:
            state["digests_done"].append(digest_key)
        if not manual:
            state["last_digest_ts"] = time.time()
    else:
        print(f"Breaking: hacen falta {min_outlets} medios "
              f"({'dia' if is_day else 'noche'})")
        posted = run_breaking(stories, recent, state, min_outlets)

    save_recent(recent)
    save_state(state)
    print(f"Terminado correctamente. Publicadas: {posted}")


if __name__ == "__main__":
    main()
