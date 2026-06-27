"""Build Persiana + Telewebion combined playlist."""
import gzip, re, urllib.request, xml.etree.ElementTree as ET

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

NEWS_CHANNELS = [
    ("#EXTINF:-1 group-title=\"📰 خبر\" tvg-logo=\"https://upload.wikimedia.org/wikipedia/commons/thumb/6/60/IranIntl_Logo.png/320px-IranIntl_Logo.png\",Iran International",
     "https://hlspackager.akamaized.net/live/DB/IRAN_INTERNATIONAL/HLS/IRAN_INTERNATIONAL.m3u8"),
    ("#EXTINF:-1 group-title=\"📰 خبر\" tvg-logo=\"https://upload.wikimedia.org/wikipedia/commons/thumb/4/42/BBC_World_News_2022.svg/320px-BBC_World_News_2022.svg.png\",BBC World News",
     "https://cdn-7.pishow.tv/live/429/master.m3u8"),
    ("#EXTINF:-1 group-title=\"📰 خبر\" tvg-logo=\"https://upload.wikimedia.org/wikipedia/en/thumb/f/f2/Al_Jazeera_English_logo.svg/320px-Al_Jazeera_English_logo.svg.png\",Al Jazeera English",
     "https://live-hls-apps-aje-fa.getaj.net/AJE/index.m3u8"),
    ("#EXTINF:-1 group-title=\"📰 خبر\" tvg-logo=\"https://upload.wikimedia.org/wikipedia/ar/thumb/1/10/AlJazeera.svg/320px-AlJazeera.svg.png\",Al Jazeera Arabic",
     "https://live-hls-apps-aja-fa.getaj.net/AJA/01.m3u8"),
    ("#EXTINF:-1 group-title=\"📰 خبر\" tvg-logo=\"https://upload.wikimedia.org/wikipedia/commons/thumb/8/8e/Sky_News_Arabia_logo.svg/320px-Sky_News_Arabia_logo.svg.png\",Sky News Arabia",
     "https://live-stream.skynewsarabia.com/c-horizontal-channel/horizontal-stream/index.m3u8"),
    ("#EXTINF:-1 group-title=\"📰 خبر\" tvg-logo=\"https://upload.wikimedia.org/wikipedia/commons/thumb/b/b3/Al_Arabiya_logo.svg/320px-Al_Arabiya_logo.svg.png\",Al Arabiya English",
     "https://live.alarabiya.net/alarabiapublish/english/playlist_dvr.m3u8"),
    ("#EXTINF:-1 group-title=\"📰 خبر\" tvg-logo=\"https://upload.wikimedia.org/wikipedia/commons/thumb/b/b3/Al_Arabiya_logo.svg/320px-Al_Arabiya_logo.svg.png\",Al Arabiya Al Hadath",
     "https://av.alarabiya.net/alarabiapublish/alhadath.smil/playlist.m3u8"),
    ("#EXTINF:-1 group-title=\"📰 خبر\" tvg-logo=\"https://upload.wikimedia.org/wikipedia/commons/thumb/2/24/France_24_logo.svg/320px-France_24_logo.svg.png\",France 24 English",
     "https://static.france24.com/live/F24_EN_LO_HLS/live_web.m3u8"),
    ("#EXTINF:-1 group-title=\"📰 خبر\" tvg-logo=\"https://upload.wikimedia.org/wikipedia/commons/thumb/2/24/France_24_logo.svg/320px-France_24_logo.svg.png\",France 24 Arabic",
     "https://static.france24.com/live/F24_AR_LO_HLS/live_web.m3u8"),
    ("#EXTINF:-1 group-title=\"📰 خبر\" tvg-logo=\"https://upload.wikimedia.org/wikipedia/commons/thumb/7/75/DW_logo_2012.svg/320px-DW_logo_2012.svg.png\",DW English",
     "https://dwamdstream102.akamaized.net/hls/live/2015525/dwstream102/index.m3u8"),
    ("#EXTINF:-1 group-title=\"📰 خبر\" tvg-logo=\"https://upload.wikimedia.org/wikipedia/en/thumb/7/74/Euronews_logo.svg/320px-Euronews_logo.svg.png\",Euronews English",
     "https://rbmn-live.akamaized.net/hls/live/590964/BoRB-AT/master.m3u8"),
    ("#EXTINF:-1 group-title=\"📰 خبر\" tvg-logo=\"https://upload.wikimedia.org/wikipedia/commons/thumb/6/6b/CGTN.svg/320px-CGTN.svg.png\",CGTN English",
     "https://news.cgtn.com/resource/live/english/cgtn-news.m3u8"),
    ("#EXTINF:-1 group-title=\"📰 خبر\" tvg-logo=\"https://upload.wikimedia.org/wikipedia/commons/thumb/1/14/RT_logo_2021.svg/320px-RT_logo_2021.svg.png\",RT International",
     "https://rt-glb.rttv.com/live/rtnews/playlist.m3u8"),
]


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


def main():
    build_epg()
    epg_url = "https://raw.githubusercontent.com/Samhouston010/persian-tv/master/epg.xml.gz"
    out = [f'#EXTM3U url-tvg="{epg_url}"', ""]
    total = 0
    for group, url in SOURCES:
        text = fetch(url).decode("utf-8", errors="ignore")
        entries = list(extract(text, group))
        for extinf, stream in entries:
            out.append(extinf); out.append(stream); out.append("")
        total += len(entries)
        print(f"{group}: {len(entries)} channels", flush=True)
    for extinf, stream in NEWS_CHANNELS:
        out.append(extinf); out.append(stream); out.append("")
    total += len(NEWS_CHANNELS)
    print(f"News: {len(NEWS_CHANNELS)} channels", flush=True)
    with open("playlist.m3u", "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    print(f"Total: {total}", flush=True)


if __name__ == "__main__":
    main()
