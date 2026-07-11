"""Build Persiana + Telewebion combined playlist."""
import gzip, html, json, os, re, time, urllib.error, urllib.request, xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed

IRAN_INTL_SITEMAP  = "https://www.iranintl.com/sitemap-videos.xml"
FOX26_SITEMAP_BASE = "https://www.fox26houston.com/sitemap.xml?type=videos"
FOX26_LOGO         = "https://raw.githubusercontent.com/tv-logo/tv-logos/main/countries/united-states/us-local/fox-26-kriv-us.png"
NAMAKADE_MOVIES_URL = "https://namakade.com/movies"
ARTE_SITEMAP = "https://www.arte.tv/static/opa_static/sitemap/en_programs.xml"
ARTE_API = "https://api.arte.tv/api/player/v2/config/en"

# ponytail: Aparat's own HLS manifest tokens expire in ~5h, so entries point at a
# Worker (aparat-vod-proxy) that re-resolves a fresh link per play, same as Sepehr VOD.
APARAT_PROXY_BASE = "https://aparat-vod-proxy.samhouston010.workers.dev"
# curated "full movie" playlists (found via search, spanning genres) -- Aparat has no
# movie-category API like Sepehr's, so this is the closest equivalent. Max quality on
# Aparat tops out at 720p platform-wide (verified against ~60 videos incl. ones titled
# "1080p HD") -- there is no true 1080p to filter for.
APARAT_MOVIE_PLAYLISTS = [
    276140, 22120472, 492423, 6193963, 596480, 491715, 349482, 4446258, 259766, 243450,
    1030868, 348420, 23420922, 10115234, 1874423, 12062357, 6625238, 9753476, 853106,
    493601, 354624, 11895670, 851074, 491733, 655135, 388745,
]


def _aparat_alive(uid):
    """Pirated-movie reuploads get taken down often -- the playlist API's cached
    listing lags behind removals (~35% of a batch were already 404 on Aparat's own
    show endpoint), so confirm each one still resolves before publishing it."""
    try:
        d = json.loads(fetch(f"https://www.aparat.com/api/fa/v1/video/video/show/videohash/{uid}"))
    except Exception:
        return False
    return not isinstance(d.get("data"), list)


def fetch_aparat_vod(workers=15):
    """Returns (entries, epg_tv_element). Aparat's playlist API already gives a
    synopsis per video, so a synthetic EPG entry (same trick as Sepehr VOD -- a
    fake 24h-wide 'now playing' window, since VOD has no real airtime) lets
    TiviMate's Info panel show it."""
    seen = set()
    candidates = []
    for pid in APARAT_MOVIE_PLAYLISTS:
        try:
            data = json.loads(fetch(f"https://www.aparat.com/api/fa/v1/video/playlist/one/playlist_id/{pid}"))
        except Exception as e:
            print(f"Aparat playlist {pid} failed: {e}", flush=True)
            continue
        for item in data.get("included") or []:
            if item.get("type") != "Video":
                continue
            a = item["attributes"]
            vid, uid = a.get("id"), a.get("uid")
            if not uid or vid in seen or a.get("process") != "done":
                continue
            try:
                if int(a.get("duration") or 0) < 1200:  # skip trailers/clips, keep full movies (20min+)
                    continue
            except ValueError:
                continue
            title = html.unescape(a.get("title") or "").strip()
            if not title:
                continue
            seen.add(vid)
            poster = a.get("big_poster") or a.get("medium_poster") or ""
            desc = html.unescape(a.get("description") or "").strip()
            tvg_id = f"aparat{vid}"
            extinf = f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-logo="{poster}" group-title="\U0001f3ac آپارات VOD - فیلم سینمایی",{title}'
            candidates.append((uid, tvg_id, extinf, title, desc, poster))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        alive = dict(zip((u for u, *_ in candidates), pool.map(_aparat_alive, (u for u, *_ in candidates))))
    dead = sum(1 for u, *_ in candidates if not alive[u])
    if dead:
        print(f"Aparat VOD: dropped {dead} dead/removed videos", flush=True)
    live = [c for c in candidates if alive[c[0]]]
    entries = [(extinf, f"{APARAT_PROXY_BASE}/play/{uid}") for uid, tvg_id, extinf, title, desc, poster in live]

    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    epg_start = (now - timedelta(hours=12)).strftime("%Y%m%d%H%M%S +0000")
    epg_stop = (now + timedelta(hours=12)).strftime("%Y%m%d%H%M%S +0000")
    tv = ET.Element("tv")
    for uid, tvg_id, extinf, title, desc, poster in live:
        ch = ET.SubElement(tv, "channel", {"id": tvg_id})
        ET.SubElement(ch, "display-name").text = title
        if poster:
            ET.SubElement(ch, "icon", {"src": poster})
        pe = ET.SubElement(tv, "programme", {"start": epg_start, "stop": epg_stop, "channel": tvg_id})
        ET.SubElement(pe, "title", {"lang": "fa"}).text = title
        if desc:
            ET.SubElement(pe, "desc", {"lang": "fa"}).text = desc
        if poster:
            ET.SubElement(pe, "icon", {"src": poster})
    return entries, tv


def fetch_fox26_vod(max_items=300):
    entries = []
    for page in range(1, 50):
        if len(entries) >= max_items:
            break
        url = FOX26_SITEMAP_BASE + (f"&page={page}" if page > 1 else "")
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=15) as r:
                xml = r.read().decode("utf-8", errors="ignore")
        except Exception as e:
            print(f"Fox26 sitemap page {page} failed: {e}", flush=True)
            break
        titles  = re.findall(r"<video:title>(.*?)</video:title>", xml)
        thumbs  = re.findall(r"<video:thumbnail_loc>(.*?)</video:thumbnail_loc>", xml)
        content = re.findall(r"<video:content_loc>(.*?)</video:content_loc>", xml)
        if not titles:
            break
        for title, thumb, stream_url in zip(titles, thumbs, content):
            if len(entries) >= max_items:
                break
            thumb = thumb or FOX26_LOGO
            extinf = f'#EXTINF:-1 group-title="\U0001f4fa Fox 26 Houston VOD" tvg-logo="{thumb}",{title}'
            entries.append((extinf, stream_url))
        if len(titles) < 10:   # last partial page
            break
    return entries


def _namakade_movie(path, workers_ignore=None):
    try:
        req = urllib.request.Request("https://namakade.com" + path, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=15) as r:
            html_text = r.read().decode("utf-8", errors="ignore")
    except Exception:
        return None
    m = re.search(r"media\.negahestan\.com/ipnx/media/movies/[A-Za-z0-9_\-]+\.mp4", html_text)
    if not m:
        return None
    title_m = re.search(r"<title>([^<]*)</title>", html_text)
    thumb_m = re.search(r'og:image" content="([^"]+)"', html_text)
    title = (title_m.group(1).split("|")[0].strip() if title_m else path.rsplit("/", 1)[-1])
    thumb = thumb_m.group(1) if thumb_m else ""
    return title, thumb, "https://" + m.group(0)


def fetch_namakade_vod(workers=15):
    """IranProud's movie catalog, mirrored at namakade.com (branded 'Negahestan' in
    page titles/media CDN). No sitemap -- the /movies page itself lists ~130 unique
    titles across its category carousels, so that single page is the crawl seed.
    Each movie's mp4 is a plain unprotected file (verified: no referer/token check,
    plays via bare curl), so entries link straight to media.negahestan.com -- no
    proxy needed, unlike Aparat/Sepehr VOD."""
    try:
        req = urllib.request.Request(NAMAKADE_MOVIES_URL, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=20) as r:
            listing = r.read().decode("utf-8", errors="ignore")
    except Exception as e:
        print(f"Namakade movies listing failed: {e}", flush=True)
        return []
    paths = sorted(set(re.findall(r'href="(/(?:iran-1-movies|movies)/[^"]+)"', listing)))
    entries = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for result in pool.map(_namakade_movie, paths):
            if not result:
                continue
            title, thumb, stream = result
            extinf = f'#EXTINF:-1 group-title="\U0001f3ac IranProud VOD" tvg-logo="{thumb}",{title}'
            entries.append((extinf, stream))
    return entries


def _arte_program(pid, _retries=4):
    err = None
    for attempt in range(_retries + 1):
        try:
            data = json.loads(fetch(f"{ARTE_API}/{pid}"))
            err = None
            break
        except urllib.error.HTTPError as e:
            err = e
            if attempt < _retries:
                # ponytail: shared CI IPs hit ARTE's rate limit much harder than a
                # home IP does (confirmed via GitHub Actions logs: 429 on ~93% of
                # requests) -- honor Retry-After when given, otherwise back off hard.
                wait = e.headers.get("Retry-After") if e.code == 429 else None
                time.sleep(float(wait) if wait else 2 ** (attempt + 1))
        except Exception as e:
            err = e
            if attempt < _retries:
                time.sleep(0.5 * (attempt + 1))
    if err is not None:
        return ("error", repr(err))
    attrs = (data.get("data") or {}).get("attributes") or {}
    meta = attrs.get("metadata") or {}
    if (meta.get("duration") or {}).get("seconds", 0) < 3000:  # ~50min -- drop clips/magazine segments
        return ("short", None)
    hls = next((s["url"] for s in (attrs.get("streams") or [])
                if s.get("protocol") == "API_HLS_NG_MA" and s.get("url")), None)
    if not hls:
        return ("nohls", None)
    title = meta.get("title") or pid
    if meta.get("subtitle"):
        title = f"{title} - {meta['subtitle']}"
    desc = (meta.get("description") or "").strip()
    images = meta.get("images") or []
    poster = images[0]["url"] if images else ""
    return ("ok", (pid, title, desc, poster, hls))


def fetch_arte_vod(workers=4):
    """ARTE (Franco-German public broadcaster) VOD. Unlike Sepehr/Aparat, streams are
    plain HLS with no session token (verified: static long-lived Cache-Control, no
    expiring query params) -- entries link straight to the CDN, no proxy needed.
    The sitemap carries no category tag, so duration >=50min is the stand-in filter
    for "real film" vs magazine/news clips (same idea as Aparat's duration cutoff)."""
    try:
        xml_ = fetch(ARTE_SITEMAP).decode("utf-8", errors="ignore")
    except Exception as e:
        print(f"ARTE sitemap failed: {e}", flush=True)
        return [], ET.Element("tv")
    pids = sorted(set(re.findall(r"/en/videos/([A-Za-z0-9-]+)/", xml_)))
    print(f"ARTE sitemap: {len(pids)} programs", flush=True)
    results = []
    counts = {}
    sample_errors = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for kind, payload in pool.map(_arte_program, pids):
            counts[kind] = counts.get(kind, 0) + 1
            if kind == "ok":
                results.append(payload)
            elif kind == "error" and len(sample_errors) < 5:
                sample_errors.append(payload)
    print(f"ARTE fetch breakdown: {counts}", flush=True)
    if sample_errors:
        print(f"ARTE sample errors: {sample_errors}", flush=True)

    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    epg_start = (now - timedelta(hours=12)).strftime("%Y%m%d%H%M%S +0000")
    epg_stop = (now + timedelta(hours=12)).strftime("%Y%m%d%H%M%S +0000")
    tv = ET.Element("tv")
    entries = []
    for pid, title, desc, poster, hls in results:
        tvg_id = f"arte{pid}"
        extinf = f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-logo="{poster}" group-title="\U0001f3ac ARTE VOD",{title}'
        entries.append((extinf, hls))
        ch = ET.SubElement(tv, "channel", {"id": tvg_id})
        ET.SubElement(ch, "display-name").text = title
        if poster:
            ET.SubElement(ch, "icon", {"src": poster})
        pe = ET.SubElement(tv, "programme", {"start": epg_start, "stop": epg_stop, "channel": tvg_id})
        ET.SubElement(pe, "title", {"lang": "en"}).text = title
        if desc:
            ET.SubElement(pe, "desc", {"lang": "en"}).text = desc
        if poster:
            ET.SubElement(pe, "icon", {"src": poster})
    return entries, tv


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
    # group=None: each entry already carries its own per-category group-title (🎬 سپهر <دسته>)
    (None, "https://raw.githubusercontent.com/Samhouston010/sepehr-irib-epg/main/sepehr_vod.m3u"),
    # ponytail: Sepehr disabled by user request 2026-07-01 — token bound to Cloudflare IP,
    # 403s outside Iran, so it never played in TiviMate anyway.
    # ("📡 سپهر",    "https://raw.githubusercontent.com/Samhouston010/sepehr-irib-epg/main/sepehr_live.m3u"),
    # apsattv.com re-publishes Whale TV+'s full lineup (~360ch) and refreshes it themselves
    # every few weeks -- fetched fresh on every daily build, so it self-updates with no extra script.
    ("🐋 وال تی وی", "https://www.apsattv.com/whaletvplus_all.m3u"),
    # apsattv.com FAST-channel dumps -- same self-update pattern (all fetched fresh on every daily build).
    # Several tuples sharing one group name just accumulate under it, no code change needed.
    # User's own notes: Orka/Metax/Galxy.TV have some geo-blocked or dead entries; Kogantvplus mostly needs an AU IP.
    ("➕ و غیره", "https://www.apsattv.com/rakutentv-uk.m3u"),
    ("➕ و غیره", "https://www.apsattv.com/rakutentv-fr.m3u"),
    ("➕ و غیره", "https://www.apsattv.com/distro.m3u"),
    ("➕ و غیره", "https://www.apsattv.com/vizio.m3u"),
    ("➕ و غیره", "https://www.apsattv.com/vidaa.m3u"),
    ("➕ و غیره", "https://www.apsattv.com/orka.m3u"),
    ("➕ و غیره", "https://www.apsattv.com/kogantvplus.m3u"),
    ("➕ و غیره", "https://www.apsattv.com/metax.m3u"),
    ("➕ و غیره", "https://www.apsattv.com/freelivesports.m3u"),
    ("➕ و غیره", "https://www.apsattv.com/galxytv.m3u"),
    ("➕ و غیره", "https://www.apsattv.com/localnow.m3u"),
    ("➕ و غیره", "https://www.apsattv.com/tclplus.m3u"),
    ("➕ و غیره", "https://www.apsattv.com/hp.m3u"),
    ("➕ و غیره", "https://www.apsattv.com/igocast.m3u"),
    ("➕ و غیره", "https://www.apsattv.com/rewardedtv.m3u"),
    ("➕ و غیره", "https://www.apsattv.com/xumo.m3u"),
    ("➕ و غیره", "https://www.apsattv.com/cineverse.m3u"),
    # ponytail: disabled by user request 2026-07-11 -- these are FAST channels (Tubi/Plex/
    # Pluto/Roku/Samsung's live-loop lineups), not real per-title VOD. User wanted VOD like
    # Aparat/Sepehr, list got too crowded with 2221 channel entries for something they didn't
    # want. Left here in case a real per-title VOD source for one of these turns up later.
    # ("🎬 فیلم رایگان جهانی", "https://raw.githubusercontent.com/BuddyChewChew/app-m3u-generator/main/playlists/tubi_all.m3u"),
    # ("🎬 فیلم رایگان جهانی", "https://raw.githubusercontent.com/BuddyChewChew/app-m3u-generator/main/playlists/plex_us.m3u"),
    # ("🎬 فیلم رایگان جهانی", "https://raw.githubusercontent.com/BuddyChewChew/app-m3u-generator/main/playlists/plutotv_us.m3u"),
    # ("🎬 فیلم رایگان جهانی", "https://raw.githubusercontent.com/BuddyChewChew/app-m3u-generator/main/playlists/roku_all.m3u"),
    # ("🎬 فیلم رایگان جهانی", "https://raw.githubusercontent.com/BuddyChewChew/app-m3u-generator/main/playlists/samsungtvplus_us.m3u"),
]

EPG_SOURCES = [
    "https://raw.githubusercontent.com/Samhouston010/persiana-tv-epg/main/persiana.xml.gz",
    "https://raw.githubusercontent.com/Samhouston010/sepehr-irib-epg/main/sepehr.xml.gz",
    "https://raw.githubusercontent.com/Samhouston010/sepehr-irib-epg/main/sepehr_vod.xml.gz",
]

GROUP_RE = re.compile(r'group-title="[^"]*"')

def _ch(name, logo, stream):
    return ('#EXTINF:-1 group-title="\U0001f4f0 خبر" tvg-logo="%s",%s' % (logo, name), stream)

def _hch(name, logo, stream):
    return ('#EXTINF:-1 group-title="\U0001f3d9 هیوستن" tvg-logo="%s",%s' % (logo, name), stream)

def _mch(name, logo, stream):
    return ('#EXTINF:-1 group-title="\U0001f3b5 موزیک عربی" tvg-logo="%s",%s' % (logo, name), stream)

def _musch(name, logo, stream):
    return ('#EXTINF:-1 group-title="\U0001f3b5 موسیقی" tvg-logo="%s",%s' % (logo, name), stream)

MUSIC_CHANNELS = [
    _musch("PMC",                           "",  "https://ca-rt.onetv.app:8443/PMCMusic/index-0.m3u8?token=onetv202"),
    _musch("PMC Royale",                    "",  "https://pmcrohls.wns.live/hls/stream.m3u8"),
    _musch("PMC (Backup)",                  "https://raw.githubusercontent.com/picons/picons/master/build-source/logos/pmc.default.svg", "https://pmchls.wns.live/hls/stream.m3u8"),
    _musch("T2 TV",                         "https://www.parsatv.com/index_files/channels/t2tv.jpg", "https://t2hls.wns.live/hls/stream.m3u8"),
    _musch("4U TV",                         "https://raw.githubusercontent.com/picons/picons/master/build-source/logos/4utv.default.png", "https://hls.4utv.live/hls/stream.m3u8"),
    _musch("Radio Javan TV",                "https://raw.githubusercontent.com/picons/picons/master/build-source/logos/radiojavan.default.svg", "https://rjtvhls.wns.live/hls/stream.m3u8"),
    _musch("Avang TV",                      "https://www.parsatv.com/index_files/channels/avang.png", "https://hls.avang.live/hls/stream.m3u8"),
    _musch("Navahang TV",                   "",  "https://hls.navahang.live/hls/stream.m3u8"),
    _musch("Sun Music",                     "https://raw.githubusercontent.com/picons/picons/master/build-source/logos/sunmusic.default.png", "https://hls.sunmusic.live/hls/stream.m3u8"),
    _musch("Music Channel",                 "http://media.boni-records.com/logo.png", "http://media.boni-records.com/index.m3u8"),
    _musch("Music ON TV", "https://www.lyngsat-logo.com/logo/tv/mm/music_on_tv.png", "https://stream01.willfonk.com/live_playlist.m3u8?cid=CS325&r=FHD&ccode=JP&m=d0:20:20:04:35:cc&t=0d6938cb3dcf4b79848bc1753a59daf1"),
    _musch("DELUXE MUSIC",                  "https://i.imgur.com/E65GQN9.png", "https://sdn-global-live-streaming-packager-cache.3qsdn.com/13456/13456_264_live.m3u8"),
    _musch("DELUXE MUSIC DANCE BY KONTOR",  "", "https://sdn-global-live-streaming-packager-cache.3qsdn.com/64733/64733_264_live.m3u8"),
    _musch("DELUXE MUSIC RAP",              "", "https://sdn-global-live-streaming-packager-cache.3qsdn.com/65183/65183_264_live.m3u8"),
    _musch("Zerouno Tv Music",              "https://i.imgur.com/r74lqW8.png", "https://5f22d76e220e1.streamlock.net/zerounotvmusic/zerounotvmusic/playlist.m3u8"),
    _musch("BIZ Music",                     "", "https://stream8.cinerama.uz/1212/tracks-v1a1/mono.m3u8"),
]


def _shallow_alive(url):
    """Master 200 + #EXTM3U only — no codec/sub-manifest checks.
    ponytail: a deep check (like houston_live's is_live_video) false-positived on
    BBC/CNN/Sky News/Al Jazeera/Bloomberg/Euronews/BFM here — their masters skip the
    RESOLUTION attribute or need per-CDN session handling that a generic checker can't
    know. A shallow check is less precise but doesn't kill channels that actually work."""
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=10) as r:
            body = r.read(2048).decode("utf-8", errors="ignore")
        return body.startswith("#EXTM3U") and "#EXT-X-ENDLIST" not in body
    except Exception:
        return False


def _alive(entries, label, workers=12):
    """Drop static entries whose stream no longer even loads (dead/timeout/non-HLS
    response) — runs on every build (cron every 4h via houston_live.yml) so a link that
    dies stays out instead of lingering forever in the source list."""
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(lambda e: (e, _shallow_alive(e[1])), entries))
    dead = [extinf.rsplit(",", 1)[-1] for (extinf, stream), ok in results if not ok]
    if dead:
        print(f"{label}: dropped dead — {', '.join(dead)}", flush=True)
    return [e for e, ok in results if ok]

# Logo CDN: github.com/tv-logo/tv-logos (PNG, no hotlink block)
_EC_LOGO = "https://upload.wikimedia.org/wikipedia/commons/c/c9/English_Club_TV_logo.png"
_EC_CHANNELS = [
    ("English Club TV HD", "https://dash2.antik.sk/live/test_ectv_hd_1200/playlist.m3u8"),
    ("English Club TV SD", "https://stream8.cinerama.uz/1442/tracks-v1a1/mono.m3u8"),
]

_L = "https://raw.githubusercontent.com/tv-logo/tv-logos/main/countries"

# ponytail: slug from ncdn.telewebion.ir/{slug}/live/ → lb-cdn.sepehrtv.ir PNG
_SL = "https://lb-cdn.sepehrtv.ir/img/channel/"
_TELE_LOGO = {
    "tv1":            _SL+"logo/Logo1plus.png",
    "tv1plus":        _SL+"logo/Logo1plus.png",
    "tv2":            _SL+"logo/2.png",
    "tv3":            _SL+"logo/tv3-min.png",
    "tv4":            _SL+"logo/4-min.png",
    "tehran":         _SL+"logo/iribtv5_min.png",
    "varzesh":        _SL+"VarzeshTV300.png",
    "sport1":         _SL+"VarzeshTV300.png",
    "sport2":         _SL+"VarzeshTV300.png",
    "sport3":         _SL+"VarzeshTV300.png",
    "sport4":         _SL+"VarzeshTV300.png",
    "ofogh":          _SL+"ofogh.png",
    "amouzesh":       _SL+"logo/Amoozesh_1402-min.png",
    "irinn":          _SL+"logo/khabar-min.png",
    "irinn2":         _SL+"logo/khabar-min.png",
    "nasim":          _SL+"logo/nasim-min.png",
    "namayesh":       _SL+"logo/namayesh-min.png",
    "mostanad":       _SL+"logo/mostanad-min.png",
    "ifilm":          _SL+"event/channel_logo/Ifilm.png",
    "quran":          _SL+"quarnlogo.png",
    "salamat":        _SL+"logo/salamat-min.png",
    "pooya":          _SL+"logo/koodak_0c3b8f58fc9cf93bfb151d9400c8f795.png",
    "omid":           _SL+"logo/omido-min.png",
    "sepehr":         _SL+"logo/sepehr_liveirib.png",
    "faratar":        _SL+"uhd_4k.png",
    "abadan":         _SL+"abadan.png",
    "aftab":          _SL+"aftab_01.png",
    "atrak":          _SL+"logo/atrak-min.png",
    "eshragh":        _SL+"eshragh.png",
    "esfahan":        _SL+"esfahan.png",
    "nesfejahan":     _SL+"esfahan.png",
    "alborz":         _SL+"logo/alborz_1402_.png",
    "ilam":           _SL+"ilam.png",
    "baran":          _SL+"baran.png",
    "jahanbin":       _SL+"logo/shahrekord__jahanbin-min.png",
    "khavaran":       _SL+"khorasanjonoobi.png",
    "khorasanrazavi": _SL+"KHORASANRAZAVI.png",
    "khalijefars":    _SL+"khalijefars.png",
    "khoozestan":     _SL+"khoozestan1.jpg",
    "dena":           _SL+"dena.png",
    "sabalan":        _SL+"ardebil.png",
    "semnan":         _SL+"logo/semnan-02.png",
    "sahand":         _SL+"sahand.png",
    "fars":           _SL+"fars.png",
    "qazvin":         _SL+"qazvin.png",
    "mahabad":        _SL+"mahabad.png",
    "hamoon":         _SL+"hamoon.png",
    "kordestan":      _SL+"kordestan1.png",
    "taban":          _SL+"taban.png",
    "kawthar":        _SL+"logo/alkowsar.png",
    "alalam":         _SL+"logo/alalam-02.png",
    "presstv":        _SL+"logo/presstv.png",
    "sabz":           _SL+"Golestan150.png",
    # channels found in extended Sepehr list
    "iribu":          _SL+"rooyatv.png",
    "sarbedaran":     _SL+"logo/sarbedaran1.png",
    "labbayk":        _SL+"shabake%20labeik%20130%20130.png",
    "habib":          _SL+"habib300-min.png",
    "golkhane":       _SL+"event/logo/golkhanelogo.png",
    "makran":         _SL+"logo/makran.png",
    "ara":            _SL+"shirran.png",
    "sina":           _SL+"HAMEDAN.png",
    "velayat":        "https://lb-cdn.sepehrtv.ir/img/news/velayat_630b3da2e98b1.png",
    "palestine":      _SL+"palestine_.png",
    "nesfejahan":     _SL+"logo/nesfejahan.png",
    "irinn2":         "https://lb-cdn.sepehrtv.ir/img/news/irinn2_64328471ba6b6.png",
    "tv1plus":        _SL+"logo/1.png",
}
_TELE_SLUG_RE = re.compile(r"telewebion\.ir/([^/]+)/live/")

def _patch_tele_logo(extinf, stream):
    m = _TELE_SLUG_RE.search(stream)
    if not m:
        return extinf
    logo = _TELE_LOGO.get(m.group(1))
    if not logo:
        return extinf
    return re.sub(r'tvg-logo="[^"]*"', f'tvg-logo="{logo}"', extinf)

_S = "https://tvpnlogopeu.samsungcloud.tv/platform/image/sourcelogo/vc/00/02/34/"
_SU = "https://tvpnlogopus.samsungcloud.tv/platform/image/sourcelogo/vc/00/02/34/"
_P = "https://images.pluto.tv/channels/"

NEWS_CHANNELS = [
    # ─── فارسی/ایرانی ───────────────────────────────────────────────────────
    _ch("Iran International",    _L+"/iran/iran-international-ir.png",           "https://hlspackager.akamaized.net/live/DB/IRAN_INTERNATIONAL/HLS/IRAN_INTERNATIONAL.m3u8"),
    _ch("Iran International (Backup)", _L+"/iran/iran-international-ir.png",     "https://dev-live.livetvstream.co.uk/LS-63503-4/index.m3u8"),
    _ch("BBC Persian",           "https://upload.wikimedia.org/wikipedia/en/4/44/BBC_News_Persian_Logo.jpg", "https://vs-hls-pushb-ww-live.akamaized.net/x=4/i=urn:bbc:pips:service:bbc_persian_tv/t=3840/v=pv14/b=5070016/main.m3u8"),
    _ch("BBC Persian (Backup)",  "https://upload.wikimedia.org/wikipedia/en/4/44/BBC_News_Persian_Logo.jpg", "https://vs-hls-pushb-ww-live.akamaized.net/x=4/i=urn:bbc:pips:service:bbc_persian_tv/mobile_wifi_main_hd_abr_v2.m3u8"),
    _ch("VOA Persian",           "https://raw.githubusercontent.com/picons/picons/master/build-source/logos/voapersian.default.png", "https://voa-ingest.akamaized.net/hls/live/2033876/tvmc07/playlist.m3u8"),
    _ch("VOA Persian (Backup)",  "https://raw.githubusercontent.com/picons/picons/master/build-source/logos/voapersian.default.png", "https://voaphls.wns.live/hls/stream.m3u8"),
    _ch("Press TV",              _L+"/iran/press-tv-ir.png",                     "https://live.presstv.ir/hls/presstv_5_482/index.m3u8"),
    _ch("DEJ TV",                "https://www.parsatv.com/index_files/channels/dejtv.jpg", "https://rdejhls.wns.live/hls/stream.m3u8"),
    _ch("MelliG TV",             "https://www.parsatv.com/index_files/channels/melligtv.jpg", "https://mellihls.wns.live/hls/stream.m3u8"),
    _ch("Radio Farda TV",        "https://raw.githubusercontent.com/picons/picons/master/build-source/logos/radiofarda.default.svg", "https://rferl-ingest.akamaized.net/hls/live/2121768/tvmc01/playlist.m3u8"),
    _ch("Khabarbin TV",          "https://www.parsatv.com/index_files/channels/khabarbin.png", "https://khbhls.wns.live/hls/stream.m3u8"),
    _ch("Tapesh",                "https://raw.githubusercontent.com/picons/picons/master/build-source/logos/pbctapesh.default.png", "https://maxtvhls.wns.live/hls/stream.m3u8"),
    # سیمای آزادی: dynamic, see load_simay_live() — refreshed every 4h so a rotated CDN URL doesn't go dead
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
    # ponytail: removed by user request 2026-07-01 — reported not playing in TiviMate.
    # URL itself returns a valid-looking HLS master (200, #EXTM3U) from here, so this is
    # likely a device/session-specific Pluto/Samsung-TVPlus auth quirk, not a dead link —
    # the generic health check below can't catch it.
    # _ch("ABC News Live",       _P+"6508be683a0d700008c534e4/colorLogoPNG.png", "https://jmp2.uk/plu-6508be683a0d700008c534e4.m3u8"),
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
    _ch("NHK World Full HD",     _L+"/international/nhk-world-hd-int.png",       "https://masterpl.hls.nhkworld.jp/hls/w/live/smarttv.m3u8"),
]


_HOUSTON_MAIN = [
    # Fox 26: Amagi CDN — stable, no token
    _hch("Fox 26 Houston",  _L+"/united-states/us-local/fox-26-kriv-us.png",  "https://cdn-uw2-prod.tsv2.amagi.tv/linear/amg00488-foxdigital-kriv-lgus/playlist.m3u8"),
]
_HOUSTON_CITY = [
    # HTV: Houston city government channels via Swagit — stable, no token
    _hch("HTV 1 Houston",   "https://www.houstontx.gov/htv/images/HTV-logo.png", "https://stream.swagit.com/live-edge/houstontx/smil:hd-16x9-2-a/playlist.m3u8"),
    _hch("HTV 2 Houston",   "https://www.houstontx.gov/htv/images/HTV-logo.png", "https://stream.swagit.com/live-edge/houstontx/smil:hd-16x9-2-b/playlist.m3u8"),
]

def load_houston_live():
    """Load dynamic Houston channels from houston_live.json (refreshed every 4h)."""
    try:
        with open("houston_live.json", encoding="utf-8") as f:
            data = json.load(f)
        return [_hch(v["name"], v["logo"], v["url"]) for v in data.values()]
    except FileNotFoundError:
        return []

def load_simay_live():
    """Load Simaye Azadi live channel from simay_live.json (refreshed every 4h)."""
    try:
        with open("simay_live.json", encoding="utf-8") as f:
            data = json.load(f)
        return [_ch(v["name"], v["logo"], v["url"]) for v in data.values()]
    except FileNotFoundError:
        return []

IRAN_ORG_SOURCES = [
    "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/ir.m3u",
    "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/ir_wnslive.m3u",
]

_IPTVORG_CHANNELS = "https://iptv-org.github.io/api/channels.json"
_IPTVORG_LOGOS = "https://iptv-org.github.io/api/logos.json"
_TVGID_RE = re.compile(r'tvg-id="([^"]*)"')
_TVGLOGO_RE = re.compile(r'tvg-logo="([^"]*)"')
_CATEGORY_ORDER = ["news", "sports", "general", "entertainment", "series", "movies",
                    "kids", "family", "animation", "music", "religious", "culture",
                    "documentary", "education", "business", "legislative", "shop"]

def load_iptvorg_meta():
    """id -> categories, id -> logo url — pulled fresh every build so new/changed
    entries in iptv-org's own database show up here automatically too."""
    try:
        channels = json.loads(fetch(_IPTVORG_CHANNELS))
    except Exception as e:
        print(f"iptv-org channels.json failed: {e}", flush=True)
        channels = []
    try:
        logos = json.loads(fetch(_IPTVORG_LOGOS))
    except Exception as e:
        print(f"iptv-org logos.json failed: {e}", flush=True)
        logos = []
    cat_by_id = {c["id"]: (c.get("categories") or []) for c in channels}
    logo_by_id = {}
    for l in logos:
        if l.get("feed") or not l.get("in_use") or l.get("format") == "SVG":
            continue
        logo_by_id.setdefault(l["channel"], l["url"])
    return cat_by_id, logo_by_id

def _fill_logo(extinf, logo_by_id):
    """Only fills a logo when tvg-id matches iptv-org AND we don't already have one —
    never overrides logos we've hand-picked elsewhere in this file."""
    m = _TVGID_RE.search(extinf)
    if not m or not m.group(1):
        return extinf
    logo = logo_by_id.get(m.group(1).split("@")[0])
    if not logo:
        return extinf
    lm = _TVGLOGO_RE.search(extinf)
    if lm:
        return extinf if lm.group(1) else _TVGLOGO_RE.sub(f'tvg-logo="{logo}"', extinf, count=1)
    return extinf.replace('tvg-id="', f'tvg-logo="{logo}" tvg-id="', 1)

def _channel_category(extinf, cat_by_id):
    m = _TVGID_RE.search(extinf)
    cats = cat_by_id.get(m.group(1).split("@")[0], []) if m else []
    for i, cat in enumerate(_CATEGORY_ORDER):
        if cat in cats:
            return i
    return len(_CATEGORY_ORDER)

def fetch_iran_org(cat_by_id, logo_by_id):
    """Iran channels from iptv-org/iptv — re-fetched and re-checked every build,
    so channels iptv-org adds show up automatically and ones that stop loading drop out.
    Sorted by category (news/sports/movies/music/...) so same-type channels sit together
    within the single ایران group, per user request."""
    entries = []
    for url in IRAN_ORG_SOURCES:
        try:
            text = fetch(url).decode("utf-8", errors="ignore")
        except Exception as e:
            print(f"Iran org source failed ({url}): {e}", flush=True)
            continue
        entries.extend(extract(text, "ایران"))
    entries = _alive(entries, "Iran (iptv-org)")
    entries = [(_fill_logo(extinf, logo_by_id), stream) for extinf, stream in entries]
    entries.sort(key=lambda e: _channel_category(e[0], cat_by_id))
    return entries


ISRAEL_M3U = "https://raw.githubusercontent.com/Samhouston010/israel-tv/master/israel.m3u"
KESHET12_WORKER = "https://keshet12.samhoustonbot.workers.dev"

ISRAEL_SKIP = {"Keshet 12 DVR", "N12 News", "Keshet 12 CC", "Kan Kids"}

def fetch_israel():
    text = fetch(ISRAEL_M3U).decode("utf-8", errors="ignore")
    entries = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("#EXTINF"):
            name = line.rsplit(",", 1)[-1].strip()
            i += 1
            while i < len(lines) and lines[i].startswith("#"):
                i += 1
            if name in ISRAEL_SKIP:
                i += 1
                continue
            if i < len(lines):
                extinf = re.sub(r'group-title="[^"]*"', 'group-title="\U0001f4e1 اسرائیل"', line)
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


def extract(text, group=None):
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("#EXTINF"):
            if group is None:
                pass  # ponytail: group=None keeps each entry's own group-title (e.g. per-category VOD source)
            elif GROUP_RE.search(line):
                line = GROUP_RE.sub(f'group-title="{group}"', line)
            else:
                line = line.replace("#EXTINF:-1", f'#EXTINF:-1 group-title="{group}"', 1)
            j = i + 1
            while j < len(lines) and (not lines[j].strip() or
                  lines[j].strip().startswith("#EXT") and not lines[j].strip().startswith("#EXTINF")):
                j += 1
            if j < len(lines) and not lines[j].strip().startswith("#"):
                yield line, lines[j].strip()
                i = j + 1; continue
        i += 1


def build_epg(extra_trees=()):
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
    for tree in extra_trees:
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
    aparat, aparat_epg = fetch_aparat_vod()
    print(f"Aparat VOD: {len(aparat)} videos", flush=True)
    arte, arte_epg = fetch_arte_vod()
    print(f"ARTE VOD: {len(arte)} videos", flush=True)
    build_epg(extra_trees=[aparat_epg, arte_epg])
    cat_by_id, logo_by_id = load_iptvorg_meta()
    print(f"iptv-org meta: {len(cat_by_id)} channels, {len(logo_by_id)} logos", flush=True)
    epg_url = "https://raw.githubusercontent.com/Samhouston010/persian-tv/master/epg.xml.gz"
    out = [f'#EXTM3U url-tvg="{epg_url}"', ""]
    total = 0
    for group, url in SOURCES:
        text = fetch(url).decode("utf-8", errors="ignore")
        entries = list(extract(text, group))
        for extinf, stream in entries:
            extinf = _patch_tele_logo(extinf, stream)
            extinf = _fill_logo(extinf, logo_by_id)
            af = _AF_TELE if "telewebion" in stream else _AF_NORMAL
            out.append(extinf); out.append(af); out.append(stream); out.append("")
        # English Club only in تلوبیون group (once)
        ec_count = 0
        if group and "تلوبیون" in group:
            for name, stream in _EC_CHANNELS:
                extinf = f'#EXTINF:-1 group-title="{group}" tvg-logo="{_EC_LOGO}",{name}'
                out.append(extinf); out.append(_AF_EC); out.append(stream); out.append("")
            ec_count = len(_EC_CHANNELS)
            # شبکه سه (بکاپ) — main ncdn.telewebion.ir/tv3 reported not working, IRIB's own CDN as backup
            tv3_extinf = '#EXTINF:-1 tvg-id="IRIB3.ir" tvg-name="شبکه سه (بکاپ)" tvg-logo="https://lb-cdn.sepehrtv.ir/img/channel/logo/tv3-min.png" group-title="%s",شبکه سه (بکاپ)' % group
            out.append(tv3_extinf); out.append(_AF_TELE); out.append("https://s1-cloud.irib.ir/securelive3/tv3hd/tv3hd.m3u8"); out.append("")
            ec_count += 1
        if group and "پرشیانا" in group:
            mbc_extinf = '#EXTINF:-1 tvg-id="" tvg-name="MBC Persia" tvg-logo="https://upload.wikimedia.org/wikipedia/commons/8/8f/MBC_Persia_Logo.png" group-title="%s",MBC Persia' % group
            out.append(mbc_extinf); out.append(_AF_NORMAL); out.append("https://shd-gcp-live.edgenextcdn.net/live/bitmovin-mbc-persia/818ee8e4b592dc497608f066d825bfb4/index.m3u8"); out.append("")
            mbc_backup_extinf = '#EXTINF:-1 tvg-id="" tvg-name="MBC Persia (بکاپ)" tvg-logo="https://upload.wikimedia.org/wikipedia/commons/8/8f/MBC_Persia_Logo.png" group-title="%s",MBC Persia (بکاپ)' % group
            out.append(mbc_backup_extinf); out.append(_AF_NORMAL); out.append("https://hls.mbcpersia.live/hls/stream.m3u8"); out.append("")
            ec_count += 2
        total += len(entries) + ec_count
        label = f" (+{ec_count} extra)" if ec_count else ""
        print(f"{group or url}: {len(entries)} channels{label}", flush=True)
    # سیمای آزادی right under Iran International (first 2 entries), not appended at the end
    news = _alive(NEWS_CHANNELS[:2], "News") + load_simay_live() + _alive(NEWS_CHANNELS[2:], "News")
    for extinf, stream in news:
        extinf = _fill_logo(extinf, logo_by_id)
        out.append(extinf); out.append(_AF_NORMAL); out.append(stream); out.append("")
    total += len(news)
    print(f"News: {len(news)} channels", flush=True)
    houston = _alive(_HOUSTON_MAIN, "Houston") + load_houston_live() + _alive(_HOUSTON_CITY, "Houston")
    for extinf, stream in houston:
        out.append(extinf); out.append(_AF_NORMAL); out.append(stream); out.append("")
    total += len(houston)
    print(f"Houston: {len(houston)} channels", flush=True)
    music = _alive(MUSIC_CHANNELS, "Music")
    for extinf, stream in music:
        out.append(extinf); out.append(_AF_NORMAL); out.append(stream); out.append("")
    total += len(music)
    print(f"Music: {len(music)} channels", flush=True)
    # ponytail: geo-blocked — needs VPN (Saudi/Middle East) active on device to stream
    _ROT_REF = "#EXTVLCOPT:http-referrer=https://rotana.net/"
    # disabled by user request 2026-07-01 — geo-blocked, no non-VPN fix yet
    arabic_music = [
        # _mch("Rotana Music",  "https://upload.wikimedia.org/wikipedia/commons/0/00/Rotana_Music_Logo.png", "https://rotana.hibridcdn.net/rotananet/music_net-7Y83PP5adWixDF93/playlist.m3u8"),
        # _mch("Rotana Clip",   "https://upload.wikimedia.org/wikipedia/commons/1/18/Rotana_Clip_Logo.png",  "https://rotana.hibridcdn.net/rotananet/clip_net-7Y83PP5adWixDF93/playlist.m3u8"),
    ]
    for extinf, stream in arabic_music:
        out.append(extinf); out.append(_ROT_REF); out.append(_AF_NORMAL); out.append(stream); out.append("")
    total += len(arabic_music)
    print(f"Arabic Music: {len(arabic_music)} channels", flush=True)
    vod = fetch_iranintl_vod()
    for extinf, stream in vod:
        out.append(extinf); out.append(stream); out.append("")
    total += len(vod)
    print(f"Iran Intl VOD: {len(vod)} videos", flush=True)
    fox26 = fetch_fox26_vod()
    # ponytail: TiviMate buckets raw .mp4 URLs into the Movies tab by file extension,
    # regardless of group-title language — renaming the group doesn't move it next to
    # channels (unlike Iran Intl VOD, which is HLS .m3u8). Single copy until Fox26 clips
    # are served as HLS (would need our own transcode/proxy, see yt-vod-proxy precedent).
    for extinf, stream in fox26:
        out.append(extinf); out.append(stream); out.append("")
    total += len(fox26)
    print(f"Fox 26 VOD: {len(fox26)} videos", flush=True)
    for extinf, stream in aparat:
        out.append(extinf); out.append(stream); out.append("")
    total += len(aparat)
    for extinf, stream in arte:
        out.append(extinf); out.append(stream); out.append("")
    total += len(arte)
    # ponytail: disabled 2026-07-11 -- confirmed dead. Every single title's mp4 URL now
    # serves the exact same 41,316,739-byte file (checked Boomerang/Enola Holmes 2/Mezon
    # Kaar/2 Rooz Dirtar), a generic notice clip telling viewers to watch on iranproud.com
    # directly. The site retired this CDN mirror; no working link exists here anymore.
    # namakade = fetch_namakade_vod()
    # for extinf, stream in namakade:
    #     out.append(extinf); out.append(stream); out.append("")
    # total += len(namakade)
    # print(f"Namakade (IranProud) VOD: {len(namakade)} videos", flush=True)
    ted = []  # ponytail: disabled until playlist is finalized
    print("TED Talks: disabled", flush=True)
    israel = fetch_israel()
    for extinf, stream in israel:
        extinf = _fill_logo(extinf, logo_by_id)
        out.append(extinf); out.append(_AF_NORMAL); out.append(stream); out.append("")
    total += len(israel)
    print(f"Israel: {len(israel)} channels", flush=True)
    iran_org = fetch_iran_org(cat_by_id, logo_by_id)
    for extinf, stream in iran_org:
        out.append(extinf); out.append(_AF_NORMAL); out.append(stream); out.append("")
    total += len(iran_org)
    print(f"Iran (iptv-org): {len(iran_org)} channels", flush=True)
    os.makedirs("ایران", exist_ok=True)
    iran_file = ["#EXTM3U", ""]
    for extinf, stream in iran_org:
        iran_file.append(extinf); iran_file.append(_AF_NORMAL); iran_file.append(stream); iran_file.append("")
    with open("ایران/ایران.m3u", "w", encoding="utf-8") as f:
        f.write("\n".join(iran_file))
    with open("playlist.m3u", "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    print(f"Total: {total}", flush=True)


if __name__ == "__main__":
    main()
