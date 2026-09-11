"""Fetch royalty-free instrumental background music from the Jamendo API.

Adapted from ytgen. Used only for COMPILED watch-videos (individual stock clips
stay silent). Instrumental, CC BY / BY-SA only (NC and ND excluded), explicit
license URL required so attribution can be written.

Env: JAMENDO_CLIENT_ID (free, https://devportal.jamendo.com/)
Config: music.mood (single-word tag), music.volume, music.dir
Cache: assets/music/jamendo_<id>.mp3 + cache/music.json (credit record)
"""
from __future__ import annotations
import json
import os
from pathlib import Path

import requests

API = "https://api.jamendo.com/v3.0"

# good satisfying/chill single-word tags (fuzzytags '+' = AND, so keep single)
DEFAULT_MOOD = "chillout"
FALLBACK_TAGS = ["chillout", "ambient", "relaxing", "lounge", "electronic", "instrumental"]


def _client_id() -> str | None:
    return os.environ.get("JAMENDO_CLIENT_ID")


def fetch(cfg, cache_dir: Path, min_duration: float = 0.0) -> dict | None:
    """Search Jamendo for an instrumental track, download to assets/music/,
    record credit. Returns {path,title,artist,url,license_url,duration} or None."""
    cid = _client_id()
    if not cid:
        print("  no JAMENDO_CLIENT_ID in env")
        return None
    music_dir = cfg.root / cfg.get("music.dir", "assets/music")
    music_dir.mkdir(parents=True, exist_ok=True)

    mood = cfg.get("music.mood", DEFAULT_MOOD) or DEFAULT_MOOD
    candidates = [mood] + [t for t in FALLBACK_TAGS if t != mood]

    dur_lo = int(min_duration) if min_duration else 30
    results, used_tag = [], None
    for tag in candidates:
        params = {
            "client_id": cid, "format": "json", "limit": 20,
            "fuzzytags": tag, "vocalinstrumental": "instrumental",
            "audioformat": "mp32", "include": "musicinfo licenses",
            "order": "popularity_total", "durationbetween": f"{dur_lo}_600",
            "ccnc": "false", "ccnd": "false",   # exclude NonCommercial + NoDerivatives
        }
        try:
            r = requests.get(f"{API}/tracks/", params=params, timeout=30)
            r.raise_for_status()
            results = r.json().get("results", [])
        except Exception as e:
            print(f"  jamendo fetch failed ({tag}): {e}")
            continue
        if results:
            used_tag = tag
            break
    if not results:
        return None
    print(f"  jamendo: matched tag '{used_tag}', {len(results)} tracks")

    # explicit license URL required (attribution is legally mandatory)
    results = [t for t in results if t.get("license_ccurl")]
    if not results:
        print("  jamendo: no track had an explicit license URL")
        return None

    long_first = [t for t in results if float(t.get("duration", 0)) >= min_duration]
    ordered = long_first + [t for t in results if t not in long_first]

    for track in ordered:
        tid = track["id"]
        dest = music_dir / f"jamendo_{tid}.mp3"
        if not dest.exists():
            ok = False
            for url in (track.get("audio"), track.get("audiodownload")):
                if not url:
                    continue
                try:
                    with requests.get(url, stream=True, timeout=120) as resp:
                        resp.raise_for_status()
                        with open(dest, "wb") as f:
                            for chunk in resp.iter_content(65536):
                                f.write(chunk)
                    if dest.stat().st_size > 10000:
                        ok = True
                        break
                except Exception as e:
                    print(f"  download failed ({tid}): {e}")
                    dest.unlink(missing_ok=True)
            if not ok:
                continue

        info = {
            "path": str(dest), "track_id": tid,
            "title": track.get("name", ""), "artist": track.get("artist_name", ""),
            "url": track.get("shareurl", ""), "license_url": track.get("license_ccurl", ""),
            "duration": float(track.get("duration", 0)),
        }
        (cache_dir / "music.json").write_text(json.dumps(info, indent=2, ensure_ascii=False))
        return info

    print("  jamendo: no downloadable track among results")
    return None


def credit_line(info: dict) -> str:
    if not info:
        return ""
    lic = info.get("license_url", "")
    return (f'Music: "{info["title"]}" by {info["artist"]} '
            f'({info["url"]}) — via Jamendo. {lic}').strip()
