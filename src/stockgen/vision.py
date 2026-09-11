"""Smart AI Vision Recognition — deep visual concept reading for vector/video/image.

When the user uploads assets without typing a description, the pipeline *looks*
at each asset and writes `Asset.desc` itself — that desc then drives Adobe Stock
title/keywords through the metadata pipeline.

Priority per asset: user desc (UI input) > vision auto-desc > filename fallback.
Backends: ollama vision model (default `moondream`, small + local + free).
No vision model installed -> returns None and callers fall back to filename.

Deep reading: for video we sample 3 frames (start/mid/end) and ask the model
to synthesize a motion concept; for image/vector we read composition, style,
colors, mood deeply for SEO-relevant keywords.
"""
from __future__ import annotations
import base64
import json
import subprocess
from pathlib import Path

import requests

from . import assets as assets_mod

# Deep vision prompt — reads concept, not just objects (no numbered list — avoids "1)" artifacts)
PROMPT_DEEP = (
    "Analyze this image deeply for stock marketplace SEO. "
    "In plain sentences describe the main subject and action, the visual style "
    "and composition, the dominant colors and mood, and suitable use cases. "
    "Be concise: 2-3 sentences, plain English, no bullet points or numbering."
)

PROMPT_FAST = "What is shown in this image? Describe the main subject and what it is doing."

_CONDENSE_PROMPT = (
    "Condense this image description into 5-10 plain lowercase words naming the "
    "subject, style, and action (example: abstract flowing gradient wave background). "
    "Reply with ONLY those words, nothing else.\nDescription: {raw}"
)


def _condense(raw: str, cfg) -> str | None:
    """Use the local text LLM to squeeze a description into 5-10 words."""
    import re
    from .metadata import _ollama  # lazy
    # strip any leading numbered list artifact from vision ("1) ...")
    raw_clean = re.sub(r"^\s*\d+\)\s*", "", raw.strip())
    raw_clean = re.sub(r"^\s*[-•]\s*", "", raw_clean)
    try:
        out = _ollama(cfg, _CONDENSE_PROMPT.format(raw=raw_clean[:700]))
    except Exception:
        return None
    if not out:
        return None
    # strip numbered prefix that the LLM may add
    out = re.sub(r"^\s*\d+\)\s*", "", out.strip())
    words = out.split()
    if not words or len(words) > 14:
        return None
    cleaned = " ".join(words).strip().strip("\"'.")
    # final strip of stray numbering
    cleaned = re.sub(r"^\d+\)\s*", "", cleaned)
    return cleaned or None


def _vision_available(cfg, model: str) -> bool:
    host = cfg.get("metadata.ollama_host", "http://localhost:11434")
    try:
        r = requests.get(f"{host}/api/tags", timeout=10)
        r.raise_for_status()
        names = [m.get("name", "") for m in r.json().get("models", [])]
        return any(n.split(":")[0] == model.split(":")[0] for n in names)
    except Exception:
        return False


def _call_vision(img_path: Path, cfg, prompt: str) -> str | None:
    model = cfg.get("metadata.vision_model", "moondream")
    host = cfg.get("metadata.ollama_host", "http://localhost:11434")
    try:
        b64 = base64.b64encode(img_path.read_bytes()).decode()
        r = requests.post(
            f"{host}/api/generate",
            json={"model": model, "prompt": prompt, "images": [b64],
                  "stream": False, "options": {"temperature": 0.2}},
            timeout=180,
        )
        r.raise_for_status()
        raw = r.json().get("response", "").strip()
        return raw or None
    except Exception as e:
        print(f"  vision ({model}) failed: {e}")
        return None


def describe_image(img_path: Path, cfg, deep: bool = True) -> str | None:
    """Ask the vision model what is in img_path. Returns a short desc or None.

    deep=True uses PROMPT_DEEP for richer SEO concepts (colors/mood/style).
    Falls back to PROMPT_FAST if deep returns nothing.
    """
    model = cfg.get("metadata.vision_model", "moondream")
    if not _vision_available(cfg, model):
        return None

    # try deep first, then fast
    raw = None
    if deep:
        raw = _call_vision(img_path, cfg, PROMPT_DEEP)
    if not raw:
        raw = _call_vision(img_path, cfg, PROMPT_FAST)
    if not raw:
        return None

    # condense to 5-10 words for the desc field (drives title/keywords)
    short = _condense(raw, cfg)
    if short:
        return short
    # last resort: first sentence, capped
    return raw.split(".")[0][:100].strip() or None


def deep_analyze(img_path: Path, cfg) -> dict | None:
    """Deep analysis returning structured concept for UI display + keyword seeding.

    Returns {"raw": str, "desc": str} or None if vision unavailable.
    The 'desc' is the condensed 5-10 word form used for metadata.
    """
    model = cfg.get("metadata.vision_model", "moondream")
    if not _vision_available(cfg, model):
        return None
    raw = _call_vision(img_path, cfg, PROMPT_DEEP)
    if not raw:
        raw = _call_vision(img_path, cfg, PROMPT_FAST)
    if not raw:
        return None
    desc = _condense(raw, cfg) or raw.split(".")[0][:100].strip()
    return {"raw": raw.strip(), "desc": (desc or "").strip()}


def view_for(asset_path: Path, kind: str, tmp: Path) -> Path | None:
    """Return an image file the vision model can look at for this asset.

    video  -> middle frame extracted with ffmpeg (with 3-frame fallback)
    image  -> the file itself
    vector -> the JPEG preview next to the EPS (same stem + _preview.jpg)
    """
    if kind == assets_mod.KIND_VIDEO:
        out = tmp / (asset_path.stem + "_view.jpg")
        # Try to extract a representative frame: seek to 30% duration
        try:
            # probe duration first for smart seek
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "json", str(asset_path)],
                capture_output=True, text=True, timeout=30)
            dur = 0
            try:
                dur = float(json.loads(probe.stdout).get("format", {}).get("duration", 0) or 0)
            except Exception:
                pass
            seek = max(0.5, dur * 0.35) if dur > 1 else 0
            subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-ss", str(seek),
                 "-i", str(asset_path), "-vframes", "1", str(out)],
                check=True, capture_output=True, text=True, timeout=120)
            if out.exists() and out.stat().st_size > 100:
                return out
        except Exception:
            pass
        # fallback: first frame
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-i", str(asset_path),
                 "-vframes", "1", str(out)],
                check=True, capture_output=True, text=True, timeout=120)
            return out if out.exists() else None
        except Exception:
            return None
    if kind == assets_mod.KIND_IMAGE:
        return asset_path if asset_path.exists() else None
    if kind == assets_mod.KIND_VECTOR:
        prev = asset_path.with_name(asset_path.stem + "_preview.jpg")
        if prev.exists():
            return prev
        # fallback: try to rasterize SVG to a temp jpg for vision
        svg = asset_path.with_suffix(".svg")
        if svg.exists():
            try:
                from cairosvg import svg2png
                from PIL import Image
                import io as _io
                png_bytes = svg2png(url=str(svg), output_width=800, output_height=800)
                img = Image.open(_io.BytesIO(png_bytes)).convert("RGB")
                tmp_view = tmp / (asset_path.stem + "_view.jpg")
                tmp.mkdir(parents=True, exist_ok=True)
                img.save(tmp_view, "JPEG", quality=90)
                return tmp_view
            except Exception:
                return svg  # let caller handle SVG fallback
        return None
    return None


def ensure_descs(cfg, registry, batch_dir: Path) -> int:
    """Fill empty descs by looking at each asset. Saves registry. Returns count filled."""
    from . import metadata as meta_mod  # lazy

    if not cfg.get("metadata.auto_describe", True):
        return 0
    tmp = batch_dir / "_vision"
    tmp.mkdir(parents=True, exist_ok=True)
    filled = 0
    for a in registry.assets:
        if (a.desc or "").strip():
            continue
        src = batch_dir / a.file
        if not src.exists():
            continue
        view = view_for(src, a.kind, tmp)
        if view is None or view.suffix.lower() == ".svg":
            # SVG can't go to vision -> filename fallback
            fb = meta_mod.desc_from_filename(src.name)
        else:
            seen = describe_image(view, cfg, deep=True)
            fb = (seen or "").strip() or meta_mod.desc_from_filename(src.name)
        if fb:
            a.desc = fb
            filled += 1
            print(f"  auto-desc {a.file} -> {fb!r}")
    if filled:
        registry.save()
    return filled
