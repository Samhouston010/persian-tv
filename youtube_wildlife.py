"""YouTube live channels (wildlife + a couple of others) -- HLS manifest URL
expires after a few hours, so it's re-resolved via yt-dlp every 10 min
(.github/workflows/youtube_wildlife.yml). Writes a standalone
youtube_wildlife.m3u, served by playlist-proxy and merged into the final
playlist by persian-tv-playlist-proxy. Despite the filename (kept for the
existing workflow/schedule), this isn't wildlife-only any more -- group is
per-channel now, see CHANNELS below.
"""
import subprocess

# ponytail: hardcoded video_id per broadcast -- if a livestream ends without a
# successor, the channel just gets skipped (no output line), not auto-rediscovered.
# 5th field (group) defaults to wildlife when omitted; 6th (logo) defaults to
# the YouTube thumbnail when omitted.
CHANNELS = [
    ("Nat Geo Animals - Predator Battles", "MiQe9ob9aDc"),
    ("Nat Geo Kids - Animal Journeys", "q5xC6wv9Ut0"),
    ("National Geographic - National Parks USA", "lJOROUvD8sU"),
    # User request 2026-09-14: Euronews Farsi found live on YouTube via
    # parsatv.com (https://www.parsatv.com/name=Euronews-Farsi), lands in
    # the same news group as Iran International/BBC Persian/VOA Persian.
    ("Euronews Farsi", "A8eHIQdTpvQ", "📰 خبر", "https://www.parsatv.com/index_files/channels/euronewstv.png"),
]

WILDLIFE_GROUP = "🐾 حیات وحش"


def get_live_url(video_id):
    try:
        # GitHub Actions' runner IPs are apparently now flagged by YouTube's
        # bot-check ("Sign in to confirm you're not a bot") -- confirmed
        # live 2026-09-14, every single channel in this file failing with
        # the exact same error on every scheduled run, not just new ones.
        # The android player client uses a different API path that doesn't
        # trigger this check, no cookies/secrets needed (the standard
        # low-risk yt-dlp community workaround for this exact message).
        r = subprocess.run(
            ["yt-dlp", "-g", "--extractor-args", "youtube:player_client=android",
             f"https://www.youtube.com/watch?v={video_id}"],
            capture_output=True, text=True, timeout=30)
        if r.stdout.strip():
            return r.stdout.strip().splitlines()[0]
        if r.stderr.strip():
            print(f"  yt-dlp stderr: {r.stderr.strip().splitlines()[-1]}")
        return None
    except Exception as e:
        print(f"  yt-dlp exception: {e}")
        return None


def main():
    lines = ["#EXTM3U"]
    for entry in CHANNELS:
        name, video_id = entry[0], entry[1]
        group = entry[2] if len(entry) > 2 else WILDLIFE_GROUP
        logo = entry[3] if len(entry) > 3 else f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
        url = get_live_url(video_id)
        if not url:
            print(f"SKIP {name} — no stream url")
            continue
        lines.append(f'#EXTINF:-1 tvg-name="{name}" tvg-logo="{logo}" group-title="{group}",{name}')
        lines.append(url)
        print(f"OK {name}")
    with open("youtube_wildlife.m3u", "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
