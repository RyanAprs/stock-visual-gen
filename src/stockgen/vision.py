"""Automatic content descriptions via a local vision model (ollama).

When the user uploads a video/image without typing a description, the pipeline
*looks* at the asset and writes `Asset.desc` itself — that desc then drives the
Adobe Stock title/keywords through the existing metadata pipeline.

Priority per asset: user desc (UI input) > vision auto-desc > filename fallback.

Backends: ollama vision model (default `moondream`, small + local + free).
No vision model installed -> returns None and callers fall back to filename.
"""
from __future__ import annotations
import base64
import subprocess
from pathlib import Path

import requests

from . import assets as assets_mod

PROMPT = "What is shown in this image? Describe the main subject and what it is doing."

_CONDENSE_PROMPT = (
    "Condense this image description into 3-8 plain lowercase words naming the "
    "subject and action (example: cartoon dog walking animation). "
    "Reply with ONLY those words, nothing else.\nDescription: {raw}"
)


def _condense(raw: str, cfg) -> str | None:
    """Use the local text LLM to squeeze a free description into 3-8 words."""
    from .metadata import _ollama  # lazy: metadata imports vision lazily too
    try:
        out = _ollama(cfg, _CONDENSE_PROMPT.format(raw=raw[:500]))
    except Exception:
        return None
    if not out:
        return None
    words = out.split()
    if not words or len(words) > 12:
        return None
    return " ".join(words).strip().strip("\"'.")


def _vision_available(cfg, model: str) -> bool:
    host = cfg.get("metadata.ollama_host", "http://localhost:11434")
    try:
        r = requests.get(f"{host}/api/tags", timeout=10)
        r.raise_for_status()
        names = [m.get("name", "") for m in r.json().get("models", [])]
        return any(n.split(":")[0] == model.split(":")[0] for n in names)
    except Exception:
        return False


def describe_image(img_path: Path, cfg) -> str | None:
    """Ask the vision model what is in img_path. Returns a short desc or None."""
    model = cfg.get("metadata.vision_model", "moondream")
    if not _vision_available(cfg, model):
        return None
    host = cfg.get("metadata.ollama_host", "http://localhost:11434")
    try:
        b64 = base64.b64encode(img_path.read_bytes()).decode()
        r = requests.post(
            f"{host}/api/generate",
            json={"model": model, "prompt": PROMPT, "images": [b64],
                  "stream": False, "options": {"temperature": 0.2}},
            timeout=180,
        )
        r.raise_for_status()
        raw = r.json().get("response", "").strip()
        if not raw:
            return None
        # moondream describes freely (a paragraph) -> squeeze via text LLM
        short = _condense(raw, cfg)
        if short:
            return short
        # last resort: first sentence, capped
        return raw.split(".")[0][:80].strip() or None
    except Exception as e:
        print(f"  vision ({model}) failed: {e}")
        return None


def view_for(asset_path: Path, kind: str, tmp: Path) -> Path | None:
    """Return an image file the vision model can look at for this asset.

    video  -> middle frame extracted with ffmpeg
    image  -> the file itself
    vector -> the JPEG preview next to the EPS (same stem + _preview.jpg)
    """
    if kind == assets_mod.KIND_VIDEO:
        out = tmp / (asset_path.stem + "_view.jpg")
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-i", str(asset_path),
                 "-vf", "select='eq(n\\,60)'", "-vframes", "1", str(out)],
                check=True, capture_output=True, text=True, timeout=120)
            # fallback: frame 60 may not exist in short clips -> take middle via thumbnail
            if not out.exists():
                raise RuntimeError("no frame")
            return out
        except Exception:
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
        svg = asset_path.with_suffix(".svg")
        if svg.exists():
            return svg
        return None
    return None


def ensure_descs(cfg, registry, batch_dir: Path) -> int:
    """Fill empty descs by looking at each asset. Saves registry. Returns count filled."""
    from . import metadata as meta_mod  # lazy: metadata imports vision? no — keep lazy anyway

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
            seen = describe_image(view, cfg)
            fb = (seen or "").strip() or meta_mod.desc_from_filename(src.name)
        if fb:
            a.desc = fb
            filled += 1
            print(f"  auto-desc {a.file} -> {fb!r}")
    if filled:
        registry.save()
    return filled
