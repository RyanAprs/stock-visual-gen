"""Raster -> vector tracing for stockgen v2 (ORIGINAL raster only).

Traces a flat raster image (PNG/JPG/WEBP) into SVG, then SVG -> EPS + JPEG
preview (reusing vector.svg_to_eps / svg_to_preview_jpg).

GUARDRAIL: only the user's OWN raster (source=original) may be vectorized here.
Tracing downloaded stock and selling the vector is infringement, so
source=download / non-sellable sources are refused.

Engines:
  vtracer (default) — color tracer, excellent for flat icons/illustrations.
  potrace           — monochrome (black/white) tracer; needs a bitmap (PBM),
                      good for silhouettes/line art.
"""
from __future__ import annotations
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

from . import assets as assets_mod
from . import vector as vector_mod

ENGINES = ("vtracer", "potrace")


def _assert_source_ok(source: str) -> None:
    if source == assets_mod.SOURCE_DOWNLOAD:
        raise assets_mod.GuardrailError(
            "refusing to vectorize source=download: tracing downloaded raster for "
            "resale is copyright infringement."
        )
    if source not in assets_mod.SELLABLE_SOURCES:
        raise assets_mod.GuardrailError(
            f"refusing to vectorize unsellable source {source!r} "
            f"(allowed: {sorted(assets_mod.SELLABLE_SOURCES)})"
        )


def _trace_vtracer(src: Path, out_svg: Path, colors: int = 8) -> None:
    import vtracer
    vtracer.convert_image_to_svg_py(
        str(src), str(out_svg),
        colormode="color",
        color_precision=max(1, min(8, colors)),
        filter_speckle=4,
        path_precision=8,
    )


def _trace_potrace(src: Path, out_svg: Path, threshold: int = 128) -> None:
    if not shutil.which("potrace"):
        raise RuntimeError("potrace not installed (brew install potrace)")
    # potrace needs a bitmap; convert to PBM via Pillow threshold
    with tempfile.TemporaryDirectory() as td:
        pbm = Path(td) / "in.pbm"
        with Image.open(src) as im:
            g = im.convert("L").point(lambda p: 255 if p > threshold else 0, mode="1")
            g.save(pbm)
        subprocess.run(["potrace", "-s", "-o", str(out_svg), str(pbm)],
                       check=True, capture_output=True, text=True)


def vectorize(src: Path, out_dir: Path, idx: int, source: str,
              engine: str = "vtracer", colors: int = 8) -> dict:
    """Trace one original raster -> SVG + EPS + JPEG preview. Returns info dict."""
    _assert_source_ok(source)
    if engine not in ENGINES:
        raise ValueError(f"unknown engine {engine!r} (allowed: {ENGINES})")
    if not src.exists():
        raise FileNotFoundError(f"raster not found: {src}")

    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"trace_{idx:03d}"
    svg_path = out_dir / f"{stem}.svg"
    if engine == "vtracer":
        _trace_vtracer(src, svg_path, colors=colors)
    else:
        _trace_potrace(src, svg_path)

    svg = svg_path.read_text()
    eps_path = vector_mod.svg_to_eps(svg, out_dir / f"{stem}.eps")
    prev_path = vector_mod.svg_to_preview_jpg(svg, out_dir / f"{stem}_preview.jpg")
    return {
        "file": eps_path.name, "svg": svg_path.name, "preview": prev_path.name,
        "engine": engine, "traced_from": src.name,
    }
