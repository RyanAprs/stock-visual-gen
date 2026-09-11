"""Assemble rendered loop clips into one continuous video + optional music.

Two output modes are chosen by the CLI:
  - 'compile': concat several loop clips into one longer video (+ music) for watching.
  - 'individual': leave clips as-is (handled by CLI, not here).
"""
from __future__ import annotations
import json
import subprocess
from pathlib import Path


def _run(cmd: list[str]):
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def _emit_cached_credit(cfg, music_path, cache_dir):
    """If this local file matches a cached Jamendo record, (re)write its credit."""
    if cache_dir is None:
        return
    mj = None
    for cand in (cache_dir / "music.json", cfg.cache_dir / "music.json"):
        if cand.exists():
            mj = cand
            break
    if not mj:
        return
    try:
        info = json.loads(mj.read_text())
        if Path(info.get("path", "")).name == Path(music_path).name:
            from . import music as music_mod
            credit = music_mod.credit_line(info)
            if credit:
                (cache_dir / "music_credit.txt").write_text(credit + "\n")
                print("  " + credit)
    except Exception:
        pass


def _find_music(cfg, cache_dir=None, min_duration=0.0) -> Path | None:
    """Local file first; else fetch from Jamendo (provider). Returns path or None."""
    mdir = cfg.root / cfg.get("music.dir", "assets/music")
    mdir.mkdir(parents=True, exist_ok=True)
    files = sorted([p for p in mdir.iterdir()
                    if p.suffix.lower() in (".mp3", ".m4a", ".wav", ".ogg")])
    if files:
        _emit_cached_credit(cfg, files[0], cache_dir)
        return files[0]
    # no local file -> try Jamendo
    if cfg.get("music.provider", "jamendo") == "jamendo" and cache_dir is not None:
        try:
            from . import music as music_mod
            info = music_mod.fetch(cfg, cache_dir, min_duration=min_duration)
            if info:
                credit = music_mod.credit_line(info)
                if credit:
                    (cache_dir / "music_credit.txt").write_text(credit + "\n")
                    print("  " + credit)
                return Path(info["path"])
        except Exception as e:
            print(f"  music fetch failed: {e}")
    return None


def compile_clips(cfg, clips: list[dict], batch_dir: Path, out_name: str = "compiled.mp4") -> Path:
    """Concat loop clips (same aspect) into one video, optionally mixing background music."""
    if not clips:
        raise ValueError("no clips to compile")

    # concat via demuxer (all clips share codec/res)
    concat_txt = batch_dir / "_concat.txt"
    concat_txt.write_text("".join(f"file '{(batch_dir / c['file']).as_posix()}'\n" for c in clips))

    out = batch_dir / out_name
    silent = batch_dir / "_silent_concat.mp4"
    _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_txt),
          "-c", "copy", "-movflags", "+faststart", str(silent)])

    total_dur = sum(float(c.get("duration", 0)) for c in clips)
    music = _find_music(cfg, cache_dir=batch_dir, min_duration=total_dur) \
        if cfg.get("music.enabled", True) else None
    if not music:
        silent.replace(out)
        concat_txt.unlink(missing_ok=True)
        return out

    # loop music to cover full duration, duck to background level, encode final
    vol = cfg.get("music.volume", 0.5)
    _run([
        "ffmpeg", "-y",
        "-i", str(silent),
        "-stream_loop", "-1", "-i", str(music),
        "-filter_complex", f"[1:a]volume={vol},afade=t=in:st=0:d=1[a]",
        "-map", "0:v", "-map", "[a]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-ar", "48000", "-ac", "2", "-shortest",
        "-movflags", "+faststart", str(out),
    ])
    silent.unlink(missing_ok=True)
    concat_txt.unlink(missing_ok=True)
    return out
