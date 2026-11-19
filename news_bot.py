import os, json, re, time, requests, feedparser

WEBHOOK = os.environ["DISCORD_WEBHOOK"]
SEEN_FILE = "seen.json"
USER_AGENT = "Mozilla/5.0 (compatible; WorldNewsBot/1.0)"

# Para quitar un medio, borra su línea entera.
# Para añadir uno, copia una línea y cambia el nombre y la URL.
FEEDS = {
    "BBC": "https://feeds.bbci.co.uk/news/world/rss.xml",
    "The Guardian": "https://www.theguardian.com/world/rss",
    "DW": "https://rss.dw.com/xml/rss-en-world",
    "Kyiv Independent": "https://kyivindependent.com/news-archive/rss/",
    "POLITICO Europe": "https://www.politico.eu/feed/",
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


def load_seen():
    try:
        with open(SEEN_FILE) as f:
            return set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def main():
    seen = load_seen()
    new_items = []

    for source, url in FEEDS.items():
        try:
            feed = feedparser.parse(url, agent=USER_AGENT)
            print(f"{source}: {len(feed.entries)} entradas")
            for e in feed.entries[:20]:
                uid = e.get("id") or e.get("link")
                if not uid or uid in seen:
                    continue
                seen.add(uid)
                text = f"{e.get('title', '')} {e.get('summary', '')}"
                if KEYWORDS.search(text):
                    new_items.append((source, e.get("title", ""), e.get("link", "")))
        except Exception as err:
            print(f"Error con {source}: {err}")

    print(f"Noticias nuevas relevantes: {len(new_items)}")

    for source, title, link in new_items[:MAX_PER_RUN]:
        requests.post(WEBHOOK, json={"content": f"📰 **{source}**: {title}\n{link}"})
        time.sleep(1.5)

    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen)[-3000:], f)


if __name__ == "__main__":
    main()
