"""Render p5.js sketches -> 4K MP4 clips via headless renderer + ffmpeg."""
from __future__ import annotations
import shutil
import subprocess
from pathlib import Path


def _run(cmd: list[str]):
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def render_clip(cfg, sketch: str, seed: int, out_mp4: Path, cache_dir: Path,
                aspect: str | None = None) -> dict:
    """Render one sketch at a seed to a seamless-loop MP4. Returns clip info."""
    w, h = cfg.dims(aspect)
    fps = cfg.get("fps", 30)
    dur = cfg.get("duration_sec", 10)
    frames = fps * dur

    sketch_path = cfg.sketches_dir / f"{sketch}.html"
    if not sketch_path.exists():
        raise FileNotFoundError(f"sketch not found: {sketch_path}")

    frame_dir = cache_dir / "frames" / f"{sketch}_{seed}"
    if frame_dir.exists():
        shutil.rmtree(frame_dir)
    frame_dir.mkdir(parents=True, exist_ok=True)

    # 1) render frames (node)
    _run([
        "node", str(cfg.root / "render.js"), str(sketch_path),
        "--out", str(frame_dir),
        "--width", str(w), "--height", str(h),
        "--frames", str(frames), "--seed", str(seed),
    ])

    # 2) frames -> mp4 (H.264, yuv420p for max compatibility, high quality for stock)
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    _run([
        "ffmpeg", "-y", "-framerate", str(fps),
        "-i", str(frame_dir / "frame-%05d.png"),
        "-c:v", "libx264", "-preset", "slow", "-crf", "16",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        "-r", str(fps), str(out_mp4),
    ])

    # cleanup frames (large)
    shutil.rmtree(frame_dir, ignore_errors=True)

    return {
        "file": out_mp4.name,
        "sketch": sketch,
        "seed": seed,
        "width": w, "height": h, "fps": fps, "duration": dur,
        "aspect": aspect or "16:9",
    }
