"""Discover Simaye Azadi live HLS URL from iranntv.com — runs every 4h.
Reuses houston_live.py's page-scrape/validate logic for a single station.
Falls back to last cached URL if the page scrape fails.
"""
import json
from houston_live import discover, is_live_video

STATION = {
    "key":  "simay",
    "name": "سیمای آزادی",
    "logo": "https://www.iranntv.com/images/logo.png",
    "pages": ["https://www.iranntv.com/livestream"],
}


def main():
    try:
        with open("simay_live.json", encoding="utf-8") as f:
            cache = json.load(f)
    except FileNotFoundError:
        cache = {}

    url = discover(STATION)
    if url:
        cache[STATION["key"]] = {"name": STATION["name"], "logo": STATION["logo"], "url": url}
        print(f"  ✓ {STATION['name']}: {url[:70]}", flush=True)
    elif STATION["key"] in cache:
        if is_live_video(cache[STATION["key"]]["url"]):
            print(f"  ✓ {STATION['name']}: cached URL still live", flush=True)
        else:
            print(f"  ✗ {STATION['name']}: cached URL dead, removed", flush=True)
            del cache[STATION["key"]]
    else:
        print(f"  ✗ {STATION['name']}: not found", flush=True)

    with open("simay_live.json", "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)
    print(f"simay_live.json: {len(cache)} stations", flush=True)


if __name__ == "__main__":
    main()
