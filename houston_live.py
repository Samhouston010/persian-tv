"""Discover Houston local TV HLS URLs from station websites — runs every 4h.

Each station embeds its live HLS in the homepage HTML.
We scrape, validate, and cache in houston_live.json.
Falls back to last cached URL if the page scrape fails.
"""
import json, re, urllib.request
from urllib.parse import urljoin

HEADERS = {"User-Agent": "Mozilla/5.0"}
_L = "https://raw.githubusercontent.com/tv-logo/tv-logos/main/countries/united-states/us-local/"

STATIONS = [
    {
        "key":  "kprc",
        "name": "KPRC 2 Houston",
        "logo": _L + "kprc-2-us.png",
        "pages": ["https://www.click2houston.com/"],
    },
    {
        "key":  "khou",
        "name": "KHOU 11 Houston",
        "logo": _L + "khou-11-us.png",
        "pages": ["https://www.khou.com/"],
    },
    {
        "key":  "ktmd",
        "name": "Telemundo Houston",
        "logo": "https://raw.githubusercontent.com/tv-logo/tv-logos/main/countries/united-states/telemundo-us.png",
        "pages": [
            "https://www.telemundohouston.com/en/live",
            "https://www.telemundohouston.com/",
            "https://www.telemundohouston.com/live-stream",
        ],
    },
    {
        "key":  "kxln",
        "name": "Univision Houston",
        "logo": "https://raw.githubusercontent.com/tv-logo/tv-logos/main/countries/united-states/univision-us.png",
        "pages": [
            "https://www.univision.com/local/houston-kxln",
            "https://www.univision.com/local/houston-kxln/en-vivo",
        ],
    },
]

M3U8_RE = re.compile(r"(https://[^\s\"'<>]+\.m3u8[^\s\"'<>]*)")

# Clip/VOD platforms and secondary camera feeds — not the main broadcast
_SKIP = re.compile(r"(cdn\.ex\.co|mux\.com/v|brightcove|jwplatform|cdn\.jwplayer|/ADHOC-)", re.I)


def _get(url, n=8192):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=8) as r:
        return r.read(n).decode("utf-8", errors="ignore")


def is_live_video(url):
    """Return True only if URL is a live HLS VIDEO stream (not VOD, not audio-only)
    AND its actual sub-manifest resolves (catches master-playlist-only outages, e.g. SSAI backend down)."""
    try:
        body = _get(url)
        if not body.startswith("#EXTM3U"):
            return False
        if "#EXT-X-ENDLIST" in body:
            return False   # VOD
        if not re.search(r"RESOLUTION=|avc1|hvc1|hevc|VIDEO", body, re.I):
            return False
        # master playlist -> resolve first variant sub-manifest and confirm it actually has segments
        sub = next((l for l in body.splitlines() if l and not l.startswith("#")), None)
        if sub:
            sub_body = _get(urljoin(url, sub))
            if not sub_body.startswith("#EXTM3U") or "#EXTINF" not in sub_body:
                return False
        return True
    except Exception:
        return False


def discover(station):
    for page in station.get("pages", []):
        try:
            req = urllib.request.Request(page, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=20) as r:
                chunks = []
                while True:
                    c = r.read(32768)
                    if not c: break
                    chunks.append(c)
                html = b"".join(chunks).decode("utf-8", errors="ignore")
        except Exception as e:
            print(f"  {station['name']} [{page.split('/')[2]}]: {e}", flush=True)
            continue
        candidates = [u for u in M3U8_RE.findall(html) if not _SKIP.search(u)]
        for url in candidates:
            if is_live_video(url):
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
            # re-validate cached URL; keep if still live
            if is_live_video(cache[s["key"]]["url"]):
                print(f"  ✓ {s['name']}: cached URL still live", flush=True)
            else:
                print(f"  ✗ {s['name']}: cached URL dead, removed", flush=True)
                del cache[s["key"]]
        else:
            print(f"  ✗ {s['name']}: not found", flush=True)

    with open("houston_live.json", "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)
    print(f"houston_live.json: {len(cache)} stations", flush=True)


if __name__ == "__main__":
    main()
