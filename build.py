"""Build Persiana + Telewebion combined playlist."""
import gzip, json, re, urllib.request, xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta

IRAN_INTL_SITEMAP = "https://www.iranintl.com/sitemap-videos.xml"
AJE_BC_ACCT = "665003303001"
AJE_BC_PK   = ("BCpkADawqM39agLpp-TuKJ3fi2ac40ghRBmnV3-bKKuO6oZSDAbOgt4HRS5Tz"
                "FxLH2NA0XQdsoWQjrOYvmD2bVLQSYjxRgHufXokniy4kOamHBQs6UIbDSYvj2M")


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


def fetch_aljazeera_vod(days=7, workers=15):
    today = date.today()
    page_urls = set()
    for i in range(days):
        d = today - timedelta(days=i)
        sm = f"https://www.aljazeera.com/sitemap.xml?yyyy={d.year}&mm={d.month:02d}&dd={d.day:02d}"
        try:
            req = urllib.request.Request(sm, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=10) as r:
                page_urls.update(re.findall(
                    r"<loc>(https://www\.aljazeera\.com/video/[^<]+)</loc>",
                    r.read().decode("utf-8", errors="ignore")))
        except Exception:
            pass

    def get_bc_id(u):
        try:
            req = urllib.request.Request(u, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=8) as r:
                m = re.search(r"videoId=(\d{10,})", r.read().decode("utf-8", errors="ignore"))
            return m.group(1) if m else None
        except Exception:
            return None

    def get_entry(vid_id):
        api = (f"https://edge.api.brightcove.com/playback/v1/accounts/"
               f"{AJE_BC_ACCT}/videos/{vid_id}")
        for _ in range(3):
            try:
                req = urllib.request.Request(api, headers={
                    "Accept": f"application/json;pk={AJE_BC_PK}", **HEADERS})
                with urllib.request.urlopen(req, timeout=15) as r:
                    data = json.loads(r.read())
                title = data.get("name", "").strip()
                mp4 = next(
                    (s["src"] for s in data.get("sources", [])
                     if "akamaized" in s.get("src", "") and s.get("src", "").startswith("https")),
                    None)
                if not mp4:
                    return None
                return title, data.get("thumbnail", ""), mp4
            except urllib.error.HTTPError:
                return None
            except Exception:
                pass
        return None

    vid_ids = set()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for f in as_completed({pool.submit(get_bc_id, u): u for u in page_urls}):
            v = f.result()
            if v:
                vid_ids.add(v)
    print(f"AJ Brightcove IDs: {len(vid_ids)}", flush=True)

    # sequential — parallel triggers Brightcove throttling
    entries = []
    for vid_id in vid_ids:
        result = get_entry(vid_id)
        if result:
            title, thumb, mp4 = result
            extinf = (f'#EXTINF:-1 group-title="\U0001f4f9 الجزیره VOD"'
                      f' tvg-logo="{thumb}",{title}')
            entries.append((extinf, mp4))
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
        for name, stream in _EC_CHANNELS:
            extinf = f'#EXTINF:-1 group-title="{group}" tvg-logo="{_EC_LOGO}",{name}'
            out.append(extinf); out.append(_AF_EC); out.append(stream); out.append("")
        total += len(entries) + len(_EC_CHANNELS)
        print(f"{group}: {len(entries)} channels (+English Club)", flush=True)
    for extinf, stream in NEWS_CHANNELS:
        out.append(extinf); out.append(_AF_NORMAL); out.append(stream); out.append("")
    total += len(NEWS_CHANNELS)
    print(f"News: {len(NEWS_CHANNELS)} channels", flush=True)
    vod = fetch_iranintl_vod()
    for extinf, stream in vod:
        out.append(extinf); out.append(stream); out.append("")
    total += len(vod)
    print(f"Iran Intl VOD: {len(vod)} videos", flush=True)
    aj = fetch_aljazeera_vod()
    for extinf, stream in aj:
        out.append(extinf); out.append(stream); out.append("")
    total += len(aj)
    print(f"Al Jazeera VOD: {len(aj)} videos", flush=True)
    with open("playlist.m3u", "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    print(f"Total: {total}", flush=True)


if __name__ == "__main__":
    main()
