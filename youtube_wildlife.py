"""YouTube live wildlife channels -- HLS manifest URL expires after a few hours,
so it's re-resolved via yt-dlp every 10 min (.github/workflows/youtube_wildlife.yml).
Writes a standalone youtube_wildlife.m3u, served by playlist-proxy and merged into
the final playlist by persian-tv-playlist-proxy (prepended ahead of the other
🐾 حیات وحش sources so these channels land at the top of that group).
"""
import subprocess

# ponytail: hardcoded video_id per broadcast -- if a livestream ends without a
# successor, the channel just gets skipped (no output line), not auto-rediscovered.
CHANNELS = [
    ("Nat Geo Animals - Predator Battles", "MiQe9ob9aDc"),
    ("Nat Geo Kids - Animal Journeys", "q5xC6wv9Ut0"),
    ("National Geographic - National Parks USA", "lJOROUvD8sU"),
]


def get_live_url(video_id):
    try:
        r = subprocess.run(["yt-dlp", "-g", f"https://www.youtube.com/watch?v={video_id}"],
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
    for name, video_id in CHANNELS:
        url = get_live_url(video_id)
        if not url:
            print(f"SKIP {name} — no stream url")
            continue
        logo = f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
        lines.append(f'#EXTINF:-1 tvg-name="{name}" tvg-logo="{logo}" group-title="🐾 حیات وحش",{name}')
        lines.append(url)
        print(f"OK {name}")
    with open("youtube_wildlife.m3u", "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
