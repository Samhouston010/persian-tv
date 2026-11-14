# Find IRIB/Telewebion channels on NON-Telewebion servers in public m3u files (GitHub code search + big IPTV lists),
# test each link down to a video segment, then look inside every working server for more streams (open folder
# listings like cp11.adabmedia.com/hls2/). Report only -> irib_hunt.tsv. Needs `gh` logged in (or GH_TOKEN).
import json, os, re, socket, subprocess, sys, time, urllib.request, urllib.parse
from concurrent.futures import ThreadPoolExecutor

UA = {'User-Agent': 'Mozilla/5.0'}
CH = {  # channel key -> name pattern (fa + en)
    'tv1': r'شبکه ?(یک|1)\b|IRIB ?(TV)? ?1\b', 'tv2': r'شبکه ?(دو|2)\b|IRIB ?(TV)? ?2\b',
    'tv3': r'شبکه ?(سه|3)\b|IRIB ?(TV)? ?3\b', 'tv4': r'شبکه ?(چهار|4)\b|IRIB ?(TV)? ?4\b',
    'tv5': r'شبکه ?(پنج|5)\b|IRIB ?(TV)? ?5\b|Tehran TV', 'khabar': r'شبکه خبر|IRINN|IRIB ?News',
    'varzesh': r'ورزش|Varzesh|IRIB ?Sport', 'nasim': r'نسیم|Nasim', 'namayesh': r'نمایش|Namayesh',
    'tamasha': r'تماشا|Tamasha', 'ifilm': r'آی ?فیلم|i ?Film', 'mostanad': r'مستند|Mostanad|IRIB ?Doc',
    'ofogh': r'افق|Ofogh', 'pooya': r'پویا|Pouya|Pooya', 'omid': r'\bامید\b|\bOmid\b', 'quran': r'قرآن|IRIB ?Quran',
    'salamat': r'سلامت|Salamat', 'amouzesh': r'آموزش|Amoozesh|Amouzesh', 'jamejam': r'جام ?جم|Jame ?Jam',
    'shoma': r'شبکه شما|Shoma', 'razavi': r'امام رضا|Razavi', 'irankala': r'ایران ?کالا|Iran ?Kala',
}
SKIP = r'telewebion|tw-relay|samhouston|aburayhan|147-224-130-108|147\.224\.130\.108'
QUERIES = ['IRIB extension:m3u', 'IRIB extension:m3u8', 'Varzesh extension:m3u', 'IRINN extension:m3u',
           'Nasim extension:m3u', 'iFilm extension:m3u', '"شبکه سه" extension:m3u', '"شبکه ورزش" extension:m3u',
           'Tamasha extension:m3u', 'Namayesh extension:m3u']
LISTS = ['https://iptv-org.github.io/iptv/countries/ir.m3u', 'https://iptv-org.github.io/iptv/languages/fas.m3u',
         'https://raw.githubusercontent.com/Free-TV/IPTV/master/playlist.m3u8']
CAND = 'irib_candidates.json'

def get(url, t=10, cap=3_000_000):
    """ponytail: capped read -- some 'streams' are endless raw TS and would never return."""
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=t) as r:
        return r.geturl(), r.read(cap)

def check(url):
    """master -> variant -> newest segment (+ AES key). 'OK <KB>' / 'DRM' / 'FAIL <why>'."""
    try:
        for _ in range(3):
            url, b = get(url)
            if b[:1] == b'G':                       # raw TS
                return f'OK {len(b)//1024}KB'
            text = b.decode('utf-8', 'replace')
            if not text.lstrip().startswith('#EXTM3U'):
                return 'FAIL not-hls'
            if 'SAMPLE-AES' in text or 'widevine' in text.lower():
                return 'DRM'
            uris = [l.strip() for l in text.splitlines() if l.strip() and not l.startswith('#')]
            if not uris:
                return 'FAIL empty'
            if '#EXT-X-STREAM-INF' not in text:   # media playlist: fetch key + last segment
                key = re.findall(r'#EXT-X-KEY:.*?URI="([^"]+)"', text)
                if key: get(urllib.parse.urljoin(url, key[-1]))
                _, seg = get(urllib.parse.urljoin(url, uris[-1]))
                return f'OK {len(seg)//1024}KB' if len(seg) > 10_000 else 'FAIL tiny-segment'
            url = urllib.parse.urljoin(url, uris[0])
        return 'FAIL too-deep'
    except Exception as e:
        return f'FAIL {getattr(e, "code", type(e).__name__)}'

def gh_search(q):  # ~10 requests/min allowed
    r = subprocess.run(['gh', 'api', '-X', 'GET', 'search/code', '-f', f'q={q}', '-f', 'per_page=100',
                        '--jq', '.items[] | "\\(.repository.full_name)\\t\\(.path)"'],
                       capture_output=True, text=True, encoding='utf-8')
    time.sleep(7)
    return [tuple(l.split('\t')) for l in r.stdout.splitlines() if '\t' in l]

def parse(text):
    cur = None
    for l in text.splitlines():
        l = l.strip()
        if l.startswith('#EXTINF'): cur = l.rsplit(',', 1)[-1].strip()
        elif l.startswith('http') and cur: yield cur, l; cur = None

def collect():
    found = {}
    def scan(text, src):
        for name, url in parse(text):
            if re.search(SKIP, url, re.I): continue
            for k, pat in CH.items():
                if re.search(pat, name, re.I): found.setdefault(url, [k, name[:40], src]); break
    for u in LISTS:
        try: scan(get(u, 30, 50_000_000)[1].decode('utf-8', 'replace'), u.split('/')[2])
        except Exception as e: print('list fail', u, e, file=sys.stderr)
    files = {x for q in QUERIES for x in gh_search(q)}
    print(f'github files: {len(files)}', file=sys.stderr, flush=True)
    def fetch(rp):
        try: return get(f'https://raw.githubusercontent.com/{rp[0]}/HEAD/{urllib.parse.quote(rp[1])}', 20, 20_000_000)[1].decode('utf-8', 'replace'), rp[0]
        except Exception: return '', rp[0]
    with ThreadPoolExecutor(8) as ex:
        for text, repo in ex.map(fetch, files): scan(text, repo)
    return found

geo = {}
def where(host):
    if host not in geo:
        try:
            d = json.loads(get(f'https://ipinfo.io/{socket.gethostbyname(host)}/json', 8)[1])
            geo[host] = f"{d.get('country','?')} {d.get('city','')} | {d.get('org','')[:30]}"
        except Exception: geo[host] = '?'
    return geo[host]

def explore(url):
    """Open folder listing next to a working stream (or at /hls/, /hls2/, /live/) -> other .m3u8 names there."""
    p = urllib.parse.urlparse(url); base = f'{p.scheme}://{p.netloc}'
    dirs = {p.path.rsplit('/', 1)[0] + '/', '/hls/', '/hls2/', '/live/'}
    out = set()
    for d in dirs:
        try:
            _, b = get(base + d, 8, 2_000_000)
            t = b.decode('utf-8', 'replace')
            if 'Index of' in t:
                out |= {base + d + m for m in re.findall(r'href="([^"/?]+\.m3u8)"', t)}
        except Exception: pass
    return out

def main():
    if os.path.exists(CAND) and time.time() - os.path.getmtime(CAND) < 6 * 3600:
        found = json.load(open(CAND, encoding='utf-8'))
    else:
        found = collect(); json.dump(found, open(CAND, 'w', encoding='utf-8'), ensure_ascii=False)
    print(f'candidate urls: {len(found)}', file=sys.stderr, flush=True)
    done = [0, 0]
    def test(item):
        url, (k, name, src) = item
        r = check(url); done[0] += 1; done[1] += r.startswith('OK')
        if done[0] % 100 == 0: print(f'  tested {done[0]}/{len(found)}, working so far {done[1]}', file=sys.stderr, flush=True)
        host = urllib.parse.urlparse(url).hostname or '?'
        return [k, name, r, where(host) if r.startswith('OK') else '', host, url, src]
    with ThreadPoolExecutor(16) as ex:
        rows = list(ex.map(test, found.items()))
    # look inside every working server for streams nobody listed
    ok_hosts = {}
    for r in rows:
        if r[2].startswith('OK'): ok_hosts.setdefault(r[4], r[5])
    known = {r[5] for r in rows}
    with ThreadPoolExecutor(8) as ex:
        extra = {u for s in ex.map(explore, ok_hosts.values()) for u in s} - known
    print(f'working servers: {len(ok_hosts)}, new streams in open folders: {len(extra)}', file=sys.stderr, flush=True)
    with ThreadPoolExecutor(8) as ex:
        for u, r in zip(extra, ex.map(check, extra)):
            h = urllib.parse.urlparse(u).hostname
            rows.append(['(folder)', u.rsplit('/', 1)[-1], r, where(h) if r.startswith('OK') else '', h, u, 'open folder'])
    rows.sort(key=lambda r: (not r[2].startswith('OK'), r[0], r[4]))
    with open('irib_hunt.tsv', 'w', encoding='utf-8') as f:
        f.write('channel\tname\tresult\tlocation\thost\turl\tsource\n')
        for r in rows: f.write('\t'.join(r) + '\n')
    ok = [r for r in rows if r[2].startswith('OK')]
    print(f'tested {len(rows)}, working {len(ok)}')
    for r in ok: print(f'{r[0]:9} {r[1][:28]:28} {r[3][:40]:40} {r[4]}')

if __name__ == '__main__':
    main()
