"""Build Persiana + Telewebion combined playlist."""
import gzip, json, re, urllib.request, xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed

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
        # Convert MP4 URL to HLS: .../1/{vid}/{uuid}_240p.mp4 → .../1/{vid}/hls/{uuid}.m3u8
        hls = re.sub(r'/([0-9a-f-]+)_\d+p\.mp4$', r'/hls/\1.m3u8', url)
        extinf = f'#EXTINF:-1 group-title="\U0001f4f9 ایران اینترنشنال VOD" tvg-logo="{thumb}",{title}'
        entries.append((extinf, hls))
    return entries



HEADERS = {"User-Agent": "Mozilla/5.0"}

_AF_NORMAL = "\n".join([
    "#EXTVLCOPT:network-caching=2000",
    "#EXTVLCOPT:http-reconnect=true",
    "#EXTVLCOPT:http-continuous=true",
    "#KODIPROP:inputstream=inputstream.adaptive",
    "#KODIPROP:inputstream.adaptive.manifest_type=hls",
    "#KODIPROP:inputstream.adaptive.stream_selection_type=adaptive",
])
_AF_TELE = "\n".join([
    "#EXTVLCOPT:network-caching=8000",
    "#EXTVLCOPT:http-reconnect=true",
    "#EXTVLCOPT:http-continuous=true",
    "#KODIPROP:inputstream=inputstream.adaptive",
    "#KODIPROP:inputstream.adaptive.manifest_type=hls",
    "#KODIPROP:inputstream.adaptive.stream_selection_type=adaptive",
])
_AF_EC = "\n".join([
    "#EXTVLCOPT:network-caching=15000",
    "#EXTVLCOPT:http-reconnect=true",
    "#EXTVLCOPT:http-continuous=true",
    "#KODIPROP:inputstream=inputstream.adaptive",
    "#KODIPROP:inputstream.adaptive.manifest_type=hls",
    "#KODIPROP:inputstream.adaptive.stream_selection_type=adaptive",
])

SOURCES = [
    ("📺 پرشیانا", "https://raw.githubusercontent.com/Samhouston010/persiana-tv-epg/main/persiana.m3u"),
    ("📡 تلوبیون",  "https://raw.githubusercontent.com/Samhouston010/sepehr-irib-epg/main/sepehr.m3u"),
    ("📡 سپهر",    "https://raw.githubusercontent.com/Samhouston010/sepehr-irib-epg/main/sepehr_live.m3u"),
]

EPG_SOURCES = [
    "https://raw.githubusercontent.com/Samhouston010/persiana-tv-epg/main/persiana.xml.gz",
    "https://raw.githubusercontent.com/Samhouston010/sepehr-irib-epg/main/sepehr.xml.gz",
]

GROUP_RE = re.compile(r'group-title="[^"]*"')

def _ch(name, logo, stream):
    return ('#EXTINF:-1 group-title="\U0001f4f0 خبر" tvg-logo="%s",%s' % (logo, name), stream)

# Logo CDN: github.com/tv-logo/tv-logos (PNG, no hotlink block)
_EC_LOGO = "https://upload.wikimedia.org/wikipedia/commons/c/c9/English_Club_TV_logo.png"
_EC_CHANNELS = [
    ("English Club TV HD", "https://dash2.antik.sk/live/test_ectv_hd_1200/playlist.m3u8"),
    ("English Club TV SD", "https://stream8.cinerama.uz/1442/tracks-v1a1/mono.m3u8"),
]

_L = "https://raw.githubusercontent.com/tv-logo/tv-logos/main/countries"

_S = "https://tvpnlogopeu.samsungcloud.tv/platform/image/sourcelogo/vc/00/02/34/"
_SU = "https://tvpnlogopus.samsungcloud.tv/platform/image/sourcelogo/vc/00/02/34/"
_P = "https://images.pluto.tv/channels/"

NEWS_CHANNELS = [
    # ─── فارسی/ایرانی ───────────────────────────────────────────────────────
    _ch("Iran International",    _L+"/iran/iran-international-ir.png",           "https://hlspackager.akamaized.net/live/DB/IRAN_INTERNATIONAL/HLS/IRAN_INTERNATIONAL.m3u8"),
    _ch("Press TV",              _L+"/iran/press-tv-ir.png",                     "https://live.presstv.ir/hls/presstv_5_482/index.m3u8"),
    # ─── عربی ───────────────────────────────────────────────────────────────
    _ch("Al Jazeera English",    _L+"/qatar/al-jazeera-english-qa.png",          "https://live-hls-apps-aje-fa.getaj.net/AJE/index.m3u8"),
    _ch("Al Jazeera Arabic",     _L+"/qatar/al-jazeera-qa.png",                  "https://live-hls-apps-aja-fa.getaj.net/AJA/01.m3u8"),
    _ch("Sky News Arabia",       _L+"/united-arab-emirates/sky-news-arabia-ae.png", "https://live-stream.skynewsarabia.com/c-horizontal-channel/horizontal-stream/index.m3u8"),
    _ch("Al Arabiya",            _L+"/saudi-arabia/al-arabiya-sa.png",           "https://live.alarabiya.net/alarabiapublish/english/playlist_dvr.m3u8"),
    _ch("Al Hadath",             _L+"/saudi-arabia/al-arabiya-sa.png",           "https://av.alarabiya.net/alarabiapublish/alhadath.smil/playlist.m3u8"),
    _ch("Al Mayadeen",           _L+"/lebanon/al-mayadeen-lb.png",               "https://mdnlv.cdn.octivid.com/almdn/smil:mpegts.stream.smil/playlist.m3u8"),
    # ─── انگلیسی/بریتانیا ───────────────────────────────────────────────────
    _ch("BBC World News",        "http://schedulesdirect-api20141201-logos.s3.dualstack.us-east-1.amazonaws.com/stationLogos/s89542_dark_360w_270h.png", "https://vs-hls-push-ww-live.akamaized.net/x=4/i=urn:bbc:pips:service:bbc_news_channel_hd/t=3840/v=pv14/b=5070016/main.m3u8"),
    _ch("Sky News",              _P+"55b285cd2665de274553d66f/colorLogoPNG.png", "https://jmp2.uk/plu-55b285cd2665de274553d66f.m3u8"),
    _ch("GB News",               _S+"GBBB1600008R3_20250107T022831SQUARE.png",   "https://jmp2.uk/stvp-GBBB1600008R3"),
    # ─── آمریکا ──────────────────────────────────────────────────────────────
    _ch("CNN",                   _S+"GBBD8000016N_20260609T043642SQUARE.png",    "https://jmp2.uk/stvp-GBBD8000016N"),
    _ch("CNBC",                  _S+"GBBD3600001NO_20260317T034210SQUARE.png",   "https://jmp2.uk/stvp-GBBD3600001NO"),
    _ch("Bloomberg TV+",         _P+"54ff7ba69222cb1c2624c584/colorLogoPNG_1756948295813.png", "https://jmp2.uk/plu-54ff7ba69222cb1c2624c584.m3u8"),
    _ch("ABC News Live",         _P+"6508be683a0d700008c534e4/colorLogoPNG.png", "https://jmp2.uk/plu-6508be683a0d700008c534e4.m3u8"),
    # ─── اروپا ───────────────────────────────────────────────────────────────
    _ch("DW English",            "https://www.dw.com/images/icons/favicon-540x540.png", "https://i.mjh.nz/.r/dw-news.m3u8"),
    _ch("Euronews",              _P+"5ca1da6c593a5d78f0e7edce/colorLogoPNG.png", "https://jmp2.uk/plu-5ca1da6c593a5d78f0e7edce.m3u8"),
    _ch("France 24",             _S+"GBBD1100002L5_20250107T030646SQUARE.png",   "https://jmp2.uk/stvp-GBBD1100002L5"),
    _ch("BFM TV",                _S+"CH500001V2_20251209T125744SQUARE.png",      "https://jmp2.uk/stvp-CH500001V2"),
    # ─── روسیه/چین ───────────────────────────────────────────────────────────
    _ch("RT International",      _L+"/russia/rt-ru.png",                         "https://rt-glb.rttv.com/live/rtnews/playlist.m3u8"),
    _ch("CGTN",                  "https://images-1.rakuten.tv/storage/global-live-channel/translation/artwork/82a28e14-7f41-4a39-b6b9-57de69feb0ef.jpeg", "https://amg00405-rakutentv-cgtn-rakuten-i9tar.amagi.tv/master.m3u8"),
    # ─── آسیا ────────────────────────────────────────────────────────────────
    _ch("WION",                  _SU+"INBD4000058T_20260623T013446SQUARE.png",   "https://jmp2.uk/stvp-INBD4000058T"),
    _ch("India Today",           _SU+"INBC2800005X4_20260623T015135SQUARE.png",  "https://jmp2.uk/stvp-INBC2800005X4"),
    _ch("NDTV 24X7",             _SU+"INBC2800001D8_20260623T015302SQUARE.png",  "https://jmp2.uk/stvp-INBC2800001D8"),
]


ISRAEL_M3U = "https://raw.githubusercontent.com/Samhouston010/israel-tv/master/israel.m3u"
KESHET12_WORKER = "https://keshet12.samhoustonbot.workers.dev"

def fetch_israel():
    text = fetch(ISRAEL_M3U).decode("utf-8", errors="ignore")
    entries = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("#EXTINF"):
            extinf = re.sub(r'group-title="[^"]*"', 'group-title="\U0001f4e1 اسرائیل"', line)
            i += 1
            while i < len(lines) and lines[i].startswith("#"):
                i += 1
            if i < len(lines):
                url = lines[i].strip()
                if "mako-streaming.akamaized.net/direct/hls/live/2033791/k12/index.m3u8" in url:
                    url = KESHET12_WORKER
                entries.append((extinf, url))
        i += 1
    return entries


def fetch_ted_direct(workers=20):
    """TED Talks grouped by topic from www.ted.com (curator-approved list)."""
    curator_url = "https://www.ted.com/sitemaps/talks-curator-approved.xml.gz"
    try:
        req = urllib.request.Request(curator_url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=30) as r:
            data = gzip.decompress(r.read())
        slugs = set(re.findall(r"ted\.com/talks/([^<\"]+)</loc>", data.decode("utf-8", errors="ignore")))
    except Exception as e:
        print(f"TED curator sitemap: {e}", flush=True)
        return []
    print(f"TED slugs: {len(slugs)}", flush=True)

    # topics to skip as group (meta-categories, not subject areas)
    _SKIP_TOPICS = {"TEDx", "TED Fellows", "TEDx Talks", "Best of the Web",
                    "TED-Ed", "TEDMED", "TED Prize", "TED Residency",
                    "The Audacious Project", "TED Connects", "TED Books",
                    "TED Membership", "TED Idea Search", "TED en Español",
                    "Countdown", "Ideas studio", "Demo"}

    def get_talk(slug):
        try:
            req = urllib.request.Request(
                f"https://www.ted.com/talks/{slug}",
                headers={**HEADERS, "Accept-Language": "en-US,en;q=0.9"})
            with urllib.request.urlopen(req, timeout=15) as r:
                html = r.read().decode("utf-8", errors="ignore")
            hls_m = re.search(r"(https://hls\.ted\.com/[^\s\"'<>]+\.m3u8)", html)
            if not hls_m:
                return None
            hls = hls_m.group(1)
            title_m = re.search(r"<title[^>]*>([^|<]+)", html)
            thumb_m = re.search(r"(https://(?:pi|pu)\.tedcdn\.com/[^\s\"'<>]+\.jpg)", html)
            t = title_m.group(1).strip() if title_m else slug.replace("_", " ").title()
            img = thumb_m.group(1) if thumb_m else ""
            # pick first topic that's a real subject area
            all_topics = re.findall(r'"name":"([^"]+)","slug"', html)
            topic = next((tp for tp in all_topics if tp not in _SKIP_TOPICS), None)
            topic = topic.title() if topic else "TED Talks"
            group = f"\U0001f3a4 TED • {topic}"
            if re.search(r'hrefLang="fa"', html):
                t = "\U0001f1ee\U0001f1f7 " + t
            return (f'#EXTINF:-1 group-title="{group}" tvg-logo="{img}",{t}', hls)
        except Exception:
            return None

    results = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for fut in as_completed({pool.submit(get_talk, s): s for s in slugs}):
            r = fut.result()
            if r:
                results.append(r)
    print(f"TED Talks: {len(results)}", flush=True)
    return results




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
            af = _AF_TELE if "telewebion" in stream else _AF_NORMAL
            out.append(extinf); out.append(af); out.append(stream); out.append("")
        # English Club only in تلوبیون group (once)
        ec_count = 0
        if "تلوبیون" in group:
            for name, stream in _EC_CHANNELS:
                extinf = f'#EXTINF:-1 group-title="{group}" tvg-logo="{_EC_LOGO}",{name}'
                out.append(extinf); out.append(_AF_EC); out.append(stream); out.append("")
            ec_count = len(_EC_CHANNELS)
        total += len(entries) + ec_count
        label = f" (+{ec_count} English Club)" if ec_count else ""
        print(f"{group}: {len(entries)} channels{label}", flush=True)
    for extinf, stream in NEWS_CHANNELS:
        out.append(extinf); out.append(_AF_NORMAL); out.append(stream); out.append("")
    total += len(NEWS_CHANNELS)
    print(f"News: {len(NEWS_CHANNELS)} channels", flush=True)
    vod = fetch_iranintl_vod()
    for extinf, stream in vod:
        out.append(extinf); out.append(stream); out.append("")
    total += len(vod)
    print(f"Iran Intl VOD: {len(vod)} videos", flush=True)
    ted = fetch_ted_direct()
    # sort by topic (group-title) then by title — alphabetical in TiviMate
    ted.sort(key=lambda x: (x[0].split('group-title="')[1].split('"')[0], x[0].rsplit(',', 1)[-1]))
    ted_out = ["#EXTM3U", ""]
    for extinf, stream in ted:
        ted_out.append(extinf); ted_out.append(stream); ted_out.append("")
    with open("ted.m3u", "w", encoding="utf-8") as f:
        f.write("\n".join(ted_out))
    # also include TED in main playlist — single group, no topic prefix in title
    _group_re = re.compile(r'group-title="[^"]*"')
    for extinf, stream in ted:
        extinf = _group_re.sub('group-title="\U0001f4f9 TED"', extinf)
        out.append(extinf); out.append(stream); out.append("")
    total += len(ted)
    print(f"TED Talks: {len(ted)} videos → ted.m3u + playlist.m3u", flush=True)
    israel = fetch_israel()
    for extinf, stream in israel:
        out.append(extinf); out.append(_AF_NORMAL); out.append(stream); out.append("")
    total += len(israel)
    print(f"Israel: {len(israel)} channels", flush=True)
    with open("playlist.m3u", "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    print(f"Total: {total}", flush=True)


if __name__ == "__main__":
    main()
