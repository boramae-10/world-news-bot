import os, json, re, time, html, requests, feedparser

WEBHOOK = os.environ["DISCORD_WEBHOOK"]
SEEN_FILE = "seen.json"
USER_AGENT = "Mozilla/5.0 (compatible; WorldNewsBot/1.0)"


def icon(domain):
    return f"https://www.google.com/s2/favicons?domain={domain}&sz=128"


# Para quitar un medio, borra su bloque. Para añadir uno, copia un bloque y cambia los datos.
# "color" es el color de la barra lateral de la tarjeta (formato 0xRRGGBB).
FEEDS = {
    "BBC": {
        "url": "https://feeds.bbci.co.uk/news/world/rss.xml",
        "domain": "bbc.com",
        "color": 0xBB1919,
    },
    "The Guardian": {
        "url": "https://www.theguardian.com/world/rss",
        "domain": "theguardian.com",
        "color": 0x052962,
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
}

# Solo se publican noticias cuyo titular o resumen contenga alguna de estas palabras.
KEYWORDS = re.compile(
    r"ukrain|russia|putin|zelensk|\bnato\b|\biran|israel|gaza|hamas|hezbollah|"
    r"houthi|lebanon|syria|yemen|sudan|china|taiwan|korea|trump|biden|harris|"
    r"election|white house|congress|senate|kremlin|brussels|european union|\bEU\b|"
    r"macron|merz|starmer|sanction|ceasefire|cease-fire|\bwar\b|missile|drone|"
    r"nuclear|middle east|genocide|peace talks|summit|coup",
    re.IGNORECASE,
)

MAX_PER_RUN = 15  # máximo de noticias por ejecución
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


def build_embed(source, cfg, e):
    embed = {
        "author": {"name": source, "icon_url": icon(cfg["domain"])},
        "title": (e.get("title") or "")[:250],
        "url": e.get("link", ""),
        "color": cfg["color"],
    }
    desc = clean(e.get("summary", ""))
    if desc:
        embed["description"] = desc
    img = get_image(e)
    if img:
        embed["thumbnail"] = {"url": img}
    if e.get("published_parsed"):
        embed["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", e["published_parsed"])
    return embed


def post(embed):
    for _ in range(3):
        r = requests.post(WEBHOOK, json={"embeds": [embed]})
        if r.status_code == 429:
            time.sleep(float(r.json().get("retry_after", 2)) + 0.5)
            continue
        if r.status_code >= 400:
            print(f"Error Discord {r.status_code}: {r.text[:200]}")
        return


def main():
    seen = load_seen()
    new_items = []

    for source, cfg in FEEDS.items():
        try:
            feed = feedparser.parse(cfg["url"], agent=USER_AGENT)
            print(f"{source}: {len(feed.entries)} entradas")
            for e in feed.entries[:20]:
                uid = e.get("id") or e.get("link")
                if not uid or uid in seen:
                    continue
                seen.add(uid)
                text = f"{e.get('title', '')} {e.get('summary', '')}"
                if KEYWORDS.search(text):
                    new_items.append((source, cfg, e))
        except Exception as err:
            print(f"Error con {source}: {err}")

    print(f"Noticias nuevas relevantes: {len(new_items)}")

    for source, cfg, e in new_items[:MAX_PER_RUN]:
        post(build_embed(source, cfg, e))
        time.sleep(1.5)

    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen)[-3000:], f)


if __name__ == "__main__":
    main()
