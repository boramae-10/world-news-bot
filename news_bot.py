import os, json, re, time, html, requests, feedparser

WEBHOOK = os.environ["DISCORD_WEBHOOK"]
SEEN_FILE = "seen.json"
RECENT_FILE = "recent.json"
USER_AGENT = "Mozilla/5.0 (compatible; WorldNewsBot/1.0)"

# --- Ajustes anti-duplicados ---
RECENT_HOURS = 48
SIMILARITY_JACCARD = 0.5
SIMILARITY_OVERLAP = 0.75

MAX_PER_RUN = 1  # PRUEBA: subelo a 25 cuando termines de probar
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
    "Al Jazeera": {
        "url": "https://www.aljazeera.com/xml/rss/all.xml",
        "domain": "aljazeera.com",
        "color": 0xF9A825,
    },
    # --- Ciencia y tecnologia (sin filtro) ---
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
    # EXPERIMENTALES (via Google News):
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

# Solo se publican noticias con alguna de estas palabras
# (excepto los feeds con "skip_filter").
KEYWORDS = re.compile(
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
    r"drone|nuclear|genocide|peace talks|summit|\bcoup\b|"
    # Ciencia y fisica
    r"scientist|\bscience\b|scientific|physics|physicist|"
    r"quantum|particle|\bcern\b|astronom|astrophys|telescope|"
    r"\bnobel\b|genom|\bDNA\b|crispr|biotech|nuclear fusion|"
    r"fusion reactor|climate|\bvaccine|"
    # Espacio
    r"\bnasa\b|\besa\b|spacex|blue origin|rocket|satellite|"
    r"spacecraft|astronaut|asteroid|outer space|space station|"
    r"\bmoon\b|\bmars\b|\bISS\b|"
    # Tecnologia e IA
    r"artificial intelligence|\bAI\b|chatbot|chatgpt|openai|"
    r"anthropic|nvidia|semiconductor|microchip|\bGPU\b|"
    r"machine learning|\bLLM\b|robot|supercomputer|"
    r"cyberattack|cybersecurity|ransomware|\bhackers?\b|"
    r"data breach|spyware|encryption|big tech|tech giant|"
    r"\btech\b|technology|elon musk|\bgoogle\b|\bmicrosoft\b|"
    r"\btesla\b",
    re.IGNORECASE,
)

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
                text = f"{get_title(cfg, e)} {e.get('summary', '')}"
                if cfg.get("skip_filter") or KEYWORDS.search(text):
                    new_items.append((source, cfg, e))
        except Exception as err:
            print(f"Error con {source}: {err}")

    print(f"Noticias nuevas relevantes: {len(new_items)}")

    posted = 0
    for source, cfg, e in new_items:
        if posted >= MAX_PER_RUN:
            break
        title = get_title(cfg, e)
        tok = tokens(title)
        if is_duplicate(tok, recent_tokens):
            print(f"Duplicada ({source}): {title}")
            continue
        post(source, cfg, build_embed(cfg, e))
        recent.append({"t": title, "ts": time.time()})
        recent_tokens.append(tok)
        posted += 1
        time.sleep(1.5)

    save_recent(recent)
    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen)[-3000:], f)
    print(f"Terminado correctamente. Publicadas: {posted}")


if __name__ == "__main__":
    main()
