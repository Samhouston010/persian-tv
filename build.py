"""Build Persiana + Telewebion + Pluto VOD combined playlist."""
import gzip, json, re, urllib.request, uuid, xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed

HEADERS = {"User-Agent": "Mozilla/5.0"}

SOURCES = [
    ("📺 پرشیانا", "https://raw.githubusercontent.com/Samhouston010/persiana-tv-epg/main/persiana.m3u"),
    ("📡 تلوبیون",  "https://raw.githubusercontent.com/Samhouston010/sepehr-irib-epg/main/sepehr.m3u"),
]

EPG_SOURCES = [
    "https://raw.githubusercontent.com/Samhouston010/persiana-tv-epg/main/persiana.xml.gz",
    "https://raw.githubusercontent.com/Samhouston010/sepehr-irib-epg/main/sepehr.xml.gz",
]

GROUP_RE = re.compile(r'group-title="[^"]*"')


def fetch(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read()


def extract(text, group):
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("#EXTINF"):
            line = GROUP_RE.sub(f'group-title="{group}"', line)
            j = i + 1
            while j < len(lines) and (not lines[j].strip() or
                  lines[j].strip().startswith("#EXT") and not lines[j].strip().startswith("#EXTINF")):
                j += 1
            if j < len(lines) and not lines[j].strip().startswith("#"):
                yield line, lines[j].strip()
                i = j + 1; continue
        i += 1


def build_epg():
    root = ET.Element("tv")
    seen = set()
    for url in EPG_SOURCES:
        data = fetch(url)
        if url.endswith(".gz"):
            data = gzip.decompress(data)
        tree = ET.fromstring(data.decode("utf-8", errors="ignore"))
        for ch in tree.findall("channel"):
            cid = ch.get("id", "")
            if cid not in seen:
                root.append(ch); seen.add(cid)
        for prog in tree.findall("programme"):
            root.append(prog)
    xml = b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode").encode("utf-8")
    with gzip.open("epg.xml.gz", "wb", compresslevel=9) as f:
        f.write(xml)
    print(f"EPG: {len(seen)} channels", flush=True)


def _poster(val):
    if isinstance(val, str):
        return val
    if isinstance(val, dict):
        return val.get("path", "") or val.get("url", "")
    return ""


def fetch_pluto_vod():
    cid = str(uuid.uuid4())
    boot_url = (
        "https://boot.pluto.tv/v4/start?appName=web&appVersion=9.0.0"
        f"&clientID={cid}&clientModelNumber=1.0&deviceType=web&deviceDNT=0"
    )
    try:
        with urllib.request.urlopen(urllib.request.Request(boot_url, headers=HEADERS), timeout=20) as r:
            bdata = json.loads(r.read())
    except Exception as e:
        print(f"Pluto boot failed: {e}", flush=True)
        return []

    token = bdata["sessionToken"]
    sp = (bdata.get("stitcherParams", "")
          .replace("deviceModel=&", "deviceModel=web&")
          .replace("deviceMake=&", "deviceMake=web&")
          .replace("deviceVersion=&", "deviceVersion=9.0.0&"))

    vod_headers = {**HEADERS, "Authorization": f"Bearer {token}"}
    stitcher = "https://service-stitcher.clusters.pluto.tv"
    vod_base = "https://service-vod.clusters.pluto.tv/v4/vod"

    seen_movies, seen_series = set(), set()
    movies, series_list = [], []

    page = 0
    while True:
        url = f"{vod_base}/categories?includeItems=true&deviceType=web&limit=100&offset={page}"
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=vod_headers), timeout=20) as r:
                data = json.loads(r.read())
        except Exception as e:
            print(f"Pluto VOD page {page} failed: {e}", flush=True)
            break

        cats = data.get("categories", [])
        if not cats:
            break

        for cat in cats:
            for item in cat.get("items", []):
                iid = item.get("_id", "")
                itype = item.get("type", "")
                name = item.get("name", "").strip()
                if not (iid and name and itype in ("movie", "series")):
                    continue
                logo = (_poster(item.get("poster16_9")) or
                        ((item.get("covers") or [{}])[0]).get("url", "") or
                        _poster(item.get("featuredImage")))
                if itype == "movie" and iid not in seen_movies and len(movies) < 600:
                    seen_movies.add(iid)
                    path = (item.get("stitched") or {}).get("path", "")
                    if path:
                        stream = f"{stitcher}{path}?{sp}&episodeID={iid}&jwt={token}"
                        extinf = f'#EXTINF:-1 group-title="🎬 Pluto VOD Movies" tvg-logo="{logo}",{name}'
                        movies.append((extinf, stream))
                elif itype == "series" and iid not in seen_series:
                    seen_series.add(iid)
                    series_list.append((iid, name, logo))

        page += 1
        if page >= data.get("totalPages", 1):
            break

    def fetch_series_episodes(series_info):
        sid, sname, slogo = series_info
        episodes = []
        try:
            url = f"{vod_base}/series/{sid}/seasons?deviceType=web"
            with urllib.request.urlopen(urllib.request.Request(url, headers=vod_headers), timeout=20) as r:
                sdata = json.loads(r.read())
            for season in sdata.get("seasons", []):
                snum = season.get("number", 0)
                for ep in season.get("episodes", []):
                    eid = ep.get("_id", "")
                    path = (ep.get("stitched") or {}).get("path", "")
                    if not (eid and path):
                        continue
                    epname = ep.get("name", "").strip()
                    epnum = ep.get("number", 0)
                    logo = _poster(ep.get("poster16_9")) or slogo or ((ep.get("covers") or [{}])[0]).get("url", "")
                    stream = f"{stitcher}{path}?{sp}&episodeID={eid}&jwt={token}"
                    label = f"S{snum:02d}E{epnum:02d} - {epname}" if epname else f"S{snum:02d}E{epnum:02d}"
                    extinf = f'#EXTINF:-1 group-title="\U0001f4fa {sname}" tvg-logo="{logo}",{label}'
                    episodes.append((extinf, stream))
        except Exception:
            pass
        return episodes

    series_entries = []
    with ThreadPoolExecutor(max_workers=50) as pool:
        futures = {pool.submit(fetch_series_episodes, s): s for s in series_list[:60]}
        for future in as_completed(futures):
            series_entries.extend(future.result())

    print(f"Pluto VOD: {len(movies)} movies, {len(series_list)} series ({len(series_entries)} episodes)", flush=True)
    return movies + series_entries


def main():
    build_epg()
    epg_url = "https://raw.githubusercontent.com/Samhouston010/persian-tv/main/epg.xml.gz"
    out = [f'#EXTM3U url-tvg="{epg_url}"', ""]
    total = 0
    for group, url in SOURCES:
        text = fetch(url).decode("utf-8", errors="ignore")
        entries = list(extract(text, group))
        for extinf, stream in entries:
            out.append(extinf); out.append(stream); out.append("")
        total += len(entries)
        print(f"{group}: {len(entries)} channels", flush=True)

    vod = fetch_pluto_vod()
    for extinf, stream in vod:
        out.append(extinf); out.append(stream); out.append("")
    total += len(vod)

    with open("playlist.m3u", "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    print(f"Total: {total}", flush=True)


if __name__ == "__main__":
    main()
