"""Original raster-image generator for stockgen v2.

Renders a still frame from a p5.js sketch (via the same headless render.js used
for video) and exports a high-resolution sellable image in jpg / png / webp.
Output is the user's IP (source=original) -> sellable on Adobe Stock.

Adobe Stock image floor: >= 4 MP. Default 3840x2160 (8.3 MP) clears it. Images
are saved sRGB; JPEG drops alpha (no transparency allowed).
"""
from __future__ import annotations
import io
import shutil
import subprocess
from pathlib import Path

from PIL import Image

MIN_MEGAPIXELS = 4.0
FORMATS = {"jpg", "jpeg", "png", "webp"}


def _run(cmd: list[str]):
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def _to_srgb_rgb(img: Image.Image, drop_alpha: bool) -> Image.Image:
    """Flatten to sRGB; for JPEG composite alpha over white (no transparency)."""
    if drop_alpha and img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[-1])
        return bg
    if img.mode == "P":
        return img.convert("RGBA")
    return img.convert("RGB") if drop_alpha else img


def _save(img: Image.Image, out: Path, fmt: str) -> Path:
    fmt = fmt.lower()
    if fmt in ("jpg", "jpeg"):
        _to_srgb_rgb(img, drop_alpha=True).save(out, "JPEG", quality=92, subsampling=0)
    elif fmt == "png":
        img.convert("RGB").save(out, "PNG", optimize=True)
    elif fmt == "webp":
        img.convert("RGB").save(out, "WEBP", quality=92, method=6)
    else:
        raise ValueError(f"unsupported image format {fmt!r} (allowed: {sorted(FORMATS)})")
    return out


def render_image(cfg, sketch: str, seed: int, out_dir: Path, idx: int,
                 fmt: str = "jpg", aspect: str | None = None,
                 sample_frames: int = 6) -> dict:
    """Render one still image from a sketch. Returns image info dict.

    Renders `sample_frames` deterministic frames and keeps the middle one so the
    composition is 'developed' rather than the flat t=0 opening state.
    """
    fmt = fmt.lower()
    if fmt not in FORMATS:
        raise ValueError(f"unsupported format {fmt!r} (allowed: {sorted(FORMATS)})")
    w, h = cfg.dims(aspect)
    mp = (w * h) / 1_000_000
    if mp < MIN_MEGAPIXELS:
        raise ValueError(f"{w}x{h} = {mp:.1f}MP is below Adobe Stock's {MIN_MEGAPIXELS}MP image floor")

    sketch_path = cfg.sketches_dir / f"{sketch}.html"
    if not sketch_path.exists():
        raise FileNotFoundError(f"sketch not found: {sketch_path}")

    frame_dir = cfg.cache_dir / "img_frames" / f"{sketch}_{seed}"
    if frame_dir.exists():
        shutil.rmtree(frame_dir)
    frame_dir.mkdir(parents=True, exist_ok=True)

    n = max(1, sample_frames)
    _run([
        "node", str(cfg.root / "render.js"), str(sketch_path),
        "--out", str(frame_dir),
        "--width", str(w), "--height", str(h),
        "--frames", str(n), "--seed", str(seed),
    ])

    frames = sorted(frame_dir.glob("frame-*.png"))
    if not frames:
        shutil.rmtree(frame_dir, ignore_errors=True)
        raise RuntimeError(f"no frames produced for {sketch} seed={seed}")
    pick = frames[len(frames) // 2]

    out_dir.mkdir(parents=True, exist_ok=True)
    suffix = "_v" if aspect == "9:16" else ""
    out_img = out_dir / f"img_{idx:03d}{suffix}.{ 'jpg' if fmt=='jpeg' else fmt }"
    with Image.open(pick) as im:
        im.load()
        _save(im, out_img, fmt)

    shutil.rmtree(frame_dir, ignore_errors=True)
    return {
        "file": out_img.name, "sketch": sketch, "seed": seed,
        "width": w, "height": h, "aspect": aspect or "16:9",
        "format": fmt, "megapixels": round(mp, 1),
    }
