"""Build Persiana + Telewebion combined playlist."""
import gzip, re, urllib.request, xml.etree.ElementTree as ET

IRAN_INTL_SITEMAP = "https://www.iranintl.com/sitemap-videos.xml"


def fetch_iranintl_vod():
    req = urllib.request.Request(IRAN_INTL_SITEMAP, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=20) as r:
        xml = r.read().decode("utf-8", errors="ignore")
    # ponytail: regex is fine here, sitemap is structured, no need for XML parser
    titles = re.findall(r"<video:title>(.*?)</video:title>", xml)
    thumbs = re.findall(r"<video:thumbnail_loc>(.*?)</video:thumbnail_loc>", xml)
    videos = re.findall(r"<video:content_loc>(.*?)</video:content_loc>", xml)
    entries = []
    for title, thumb, url in zip(titles, thumbs, videos):
        url720 = url.replace("_240p.mp4", "_720p.mp4")
        extinf = f'#EXTINF:-1 group-title="\U0001f4f9 ایران اینترنشنال VOD" tvg-logo="{thumb}",{title}'
        entries.append((extinf, url720))
    return entries

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

def _ch(name, logo, stream):
    return ('#EXTINF:-1 group-title="\U0001f4f0 خبر" tvg-logo="%s",%s' % (logo, name), stream)

# Logo CDN: github.com/tv-logo/tv-logos (PNG, no hotlink block)
_L = "https://raw.githubusercontent.com/tv-logo/tv-logos/main/countries"

NEWS_CHANNELS = [
    _ch("Iran International",   _L+"/iran/iran-international-ir.png",           "https://hlspackager.akamaized.net/live/DB/IRAN_INTERNATIONAL/HLS/IRAN_INTERNATIONAL.m3u8"),
    _ch("BBC World News",        _L+"/united-kingdom/bbc-world-news-uk.png",     "https://cdn-7.pishow.tv/live/429/master.m3u8"),
    _ch("Al Jazeera English",    _L+"/qatar/al-jazeera-english-qa.png",          "https://live-hls-apps-aje-fa.getaj.net/AJE/index.m3u8"),
    _ch("Al Jazeera Arabic",     _L+"/qatar/al-jazeera-qa.png",                  "https://live-hls-apps-aja-fa.getaj.net/AJA/01.m3u8"),
    _ch("Sky News Arabia",       _L+"/united-arab-emirates/sky-news-arabia-ae.png", "https://live-stream.skynewsarabia.com/c-horizontal-channel/horizontal-stream/index.m3u8"),
    _ch("Al Arabiya English",    _L+"/saudi-arabia/al-arabiya-sa.png",           "https://live.alarabiya.net/alarabiapublish/english/playlist_dvr.m3u8"),
    _ch("Al Arabiya Al Hadath",  _L+"/saudi-arabia/al-arabiya-sa.png",           "https://av.alarabiya.net/alarabiapublish/alhadath.smil/playlist.m3u8"),
    _ch("Al Mayadeen",           _L+"/lebanon/al-mayadeen-lb.png",               "https://mdnlv.cdn.octivid.com/almdn/smil:mpegts.stream.smil/playlist.m3u8"),
    _ch("Press TV",              _L+"/iran/press-tv-ir.png",                     "https://live.presstv.ir/hls/presstv_5_482/index.m3u8"),
    _ch("France 24 English",     _L+"/france/france-24-fr.png",                  "https://static.france24.com/live/F24_EN_LO_HLS/live_web.m3u8"),
    _ch("France 24 Arabic",      _L+"/france/france-24-fr.png",                  "https://static.france24.com/live/F24_AR_LO_HLS/live_web.m3u8"),
    _ch("DW English",            _L+"/germany/dw-de.png",                        "https://dwamdstream102.akamaized.net/hls/live/2015525/dwstream102/index.m3u8"),
    _ch("Euronews English",      _L+"/international/euronews-int.png",           "https://rbmn-live.akamaized.net/hls/live/590964/BoRB-AT/master.m3u8"),
    _ch("CGTN English",          _L+"/china/cgtn-cn.png",                        "https://news.cgtn.com/resource/live/english/cgtn-news.m3u8"),
    _ch("RT International",      _L+"/russia/rt-ru.png",                         "https://rt-glb.rttv.com/live/rtnews/playlist.m3u8"),
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
    vod = fetch_iranintl_vod()
    for extinf, stream in vod:
        out.append(extinf); out.append(stream); out.append("")
    total += len(vod)
    print(f"Iran Intl VOD: {len(vod)} videos", flush=True)
    with open("playlist.m3u", "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    print(f"Total: {total}", flush=True)


if __name__ == "__main__":
    main()
