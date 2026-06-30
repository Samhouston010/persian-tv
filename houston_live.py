"""Discover Houston local TV HLS URLs from station websites — runs every 4h.

Each station embeds its live HLS in the homepage HTML.
We scrape, validate, and cache in houston_live.json.
Falls back to last cached URL if the page scrape fails.
"""
import json, re, urllib.request

HEADERS = {"User-Agent": "Mozilla/5.0"}
_L = "https://raw.githubusercontent.com/tv-logo/tv-logos/main/countries/united-states/us-local/"

STATIONS = [
    {
        "key":  "ktrk",
        "name": "ABC 13 Houston",
        "logo": _L + "abc-13-ktrk-us.png",
        "page": "https://abc13.com/watch/live/",
    },
    {
        "key":  "kprc",
        "name": "KPRC 2 Houston",
        "logo": _L + "kprc-2-us.png",
        "page": "https://www.click2houston.com/",
    },
    {
        "key":  "khou",
        "name": "KHOU 11 Houston",
        "logo": _L + "khou-11-us.png",
        "page": "https://www.khou.com/",
    },
]

M3U8_RE = re.compile(r"(https://[^\s\"'<>]+\.m3u8[^\s\"'<>]*)")

# Patterns that indicate ad/tracking URLs to skip
_SKIP = re.compile(r"(doubleclick\.net/ssai/event/[^/]+/master|ads\.|tracking\.|ad\.)", re.I)


def validate(url):
    """Return True if the URL is a live HLS playlist (starts with #EXTM3U)."""
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=8) as r:
            return r.read(16).startswith(b"#EXTM3U")
    except Exception:
        return False


def discover(station):
    try:
        req = urllib.request.Request(station["page"], headers=HEADERS)
        with urllib.request.urlopen(req, timeout=20) as r:
            html = r.read().decode("utf-8", errors="ignore")
    except Exception as e:
        print(f"  {station['name']}: page fetch failed — {e}", flush=True)
        return None

    candidates = M3U8_RE.findall(html)
    # prefer non-ad URLs first, then fall back to SSAI if nothing else
    ordered = [u for u in candidates if not _SKIP.search(u)] + \
              [u for u in candidates if _SKIP.search(u)]
    for url in ordered:
        if validate(url):
            return url
    return None


def main():
    try:
        with open("houston_live.json", encoding="utf-8") as f:
            cache = json.load(f)
    except FileNotFoundError:
        cache = {}

    for s in STATIONS:
        url = discover(s)
        if url:
            cache[s["key"]] = {"name": s["name"], "logo": s["logo"], "url": url}
            print(f"  ✓ {s['name']}: {url[:70]}", flush=True)
        elif s["key"] in cache:
            print(f"  ⚠ {s['name']}: using cached URL", flush=True)
        else:
            print(f"  ✗ {s['name']}: not found", flush=True)

    with open("houston_live.json", "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)
    print(f"houston_live.json: {len(cache)} stations", flush=True)


if __name__ == "__main__":
    main()
