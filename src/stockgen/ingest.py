"""Ingest externally-produced AI video (Google Flow / Veo) into a stockgen batch.

Unlike rendered clips, these are files the user generated elsewhere. They are
sellable ONLY if they come from a PAID Google Flow/Veo plan that grants
commercial rights. This module:
  - probes resolution/duration via ffprobe,
  - rejects clips below Adobe Stock's 4 MP video floor,
  - copies them into batch/video/ and registers them as source=ai_googleflow
    (which forces is_ai=True -> AI disclosure required at upload),
  - prints a commercial-rights reminder (the tool cannot verify the plan).

Downloaded stock (Pexels/Pixabay/internet) must NOT be ingested here — that is
handled by the registry guardrail (source=download is rejected).
"""
from __future__ import annotations
import json
import shutil
import subprocess
from pathlib import Path

from . import assets as assets_mod

MIN_MEGAPIXELS = 4.0
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".webm"}


def probe(path: Path) -> dict:
    """Return {width,height,duration,codec} via ffprobe (raises on failure)."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,codec_name",
         "-show_entries", "format=duration",
         "-of", "json", str(path)],
        check=True, capture_output=True, text=True,
    ).stdout
    data = json.loads(out)
    st = (data.get("streams") or [{}])[0]
    fmt = data.get("format") or {}
    w = int(st.get("width") or 0)
    h = int(st.get("height") or 0)
    dur = float(fmt.get("duration") or 0.0)
    return {"width": w, "height": h, "duration": round(dur, 2),
            "codec": st.get("codec_name", "")}


def ingest_dir(cfg, src: Path, batch: Path, source: str = assets_mod.SOURCE_AI_GOOGLEFLOW) -> dict:
    """Ingest every video file in `src` (file or dir) into batch/video/.

    Returns {"added": [...], "rejected": [(name, reason), ...]}.
    """
    if source == assets_mod.SOURCE_DOWNLOAD:
        raise assets_mod.GuardrailError(
            "refusing to ingest source=download: downloaded stock is not your IP "
            "and cannot be sold on Adobe Stock."
        )
    if source not in assets_mod.SELLABLE_SOURCES:
        raise assets_mod.GuardrailError(
            f"unknown/unsellable ingest source {source!r} "
            f"(allowed: {sorted(assets_mod.SELLABLE_SOURCES)})"
        )

    files = [src] if src.is_file() else sorted(
        f for f in src.iterdir() if f.suffix.lower() in VIDEO_EXTS
    )
    if not files:
        raise FileNotFoundError(f"no video files found in {src}")

    vid_dir = batch / "video"
    vid_dir.mkdir(parents=True, exist_ok=True)
    reg = assets_mod.Registry.load(batch)
    idx = len(reg.of_kind(assets_mod.KIND_VIDEO))

    added, rejected = [], []
    for f in files:
        try:
            info = probe(f)
        except Exception as e:
            rejected.append((f.name, f"ffprobe failed: {e}"))
            continue
        mp = (info["width"] * info["height"]) / 1_000_000
        if mp < MIN_MEGAPIXELS:
            rejected.append((f.name, f"{info['width']}x{info['height']} = {mp:.1f}MP "
                                     f"< {MIN_MEGAPIXELS}MP Adobe Stock video floor"))
            continue
        idx += 1
        aspect = "9:16" if info["height"] > info["width"] else "16:9"
        suffix = "_v" if aspect == "9:16" else ""
        dest = vid_dir / f"ai_{idx:03d}{suffix}{f.suffix.lower()}"
        shutil.copy2(f, dest)
        reg.add(assets_mod.Asset(
            file=f"video/{dest.name}", kind=assets_mod.KIND_VIDEO,
            source=source, sketch="nebula",  # neutral vocab seed for metadata
            seed=idx, width=info["width"], height=info["height"], aspect=aspect,
        ))
        reg.save()
        added.append({"src": f.name, "dest": dest.name, "mp": round(mp, 1),
                      "duration": info["duration"]})
    return {"added": added, "rejected": rejected}
