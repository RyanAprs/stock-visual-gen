"""Original flat-vector generator + SVG->EPS conversion for stockgen v2.

Generates 100% ORIGINAL flat icons / geometric illustrations parametrically from
a seed (the user's IP -> sellable on Adobe Stock), then converts SVG -> EPS
(Adobe Stock's required vector upload format) + a JPEG preview.

SVG->EPS uses cairosvg's PS surface (EPS is an encapsulated PostScript header).
cairocffi needs Homebrew's libcairo; if the dynamic loader can't find it we
re-exec once with DYLD_FALLBACK_LIBRARY_PATH pointing at common brew lib dirs.
"""
from __future__ import annotations
import colorsys
import io
import math
import os
import random
import sys
from pathlib import Path

# --- libcairo bootstrap (macOS: dyld must see brew lib BEFORE cairocffi loads) --
_LIB_DIRS = ["/opt/homebrew/lib", "/usr/local/lib"]


def _ensure_cairo():
    """Import cairosvg, re-exec with DYLD_FALLBACK_LIBRARY_PATH if libcairo is hidden."""
    try:
        import cairosvg  # noqa: F401
        return
    except OSError:
        if os.environ.get("_STOCKGEN_CAIRO_REEXEC"):
            raise  # already retried, give up with the real error
        extra = os.pathsep.join(d for d in _LIB_DIRS if Path(d).exists())
        cur = os.environ.get("DYLD_FALLBACK_LIBRARY_PATH", "")
        os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = os.pathsep.join(p for p in (extra, cur) if p)
        os.environ["_STOCKGEN_CAIRO_REEXEC"] = "1"
        os.execv(sys.executable, [sys.executable] + sys.argv)


# --- palette (matches metadata PALETTE_WORDS seed % 5) -----------------------
PALETTES = {
    0: ["#1b3a6b", "#2f6fb0", "#5aa9e6", "#a7d3f2"],   # blue/ocean
    1: ["#3a1b6b", "#7a3fb0", "#b06fe6", "#d8a7f2"],   # violet/nebula
    2: ["#6b4a1b", "#b0842f", "#e6c05a", "#f2e0a7"],   # gold/amber
    3: ["#1b6b3a", "#2fb06f", "#5ae6a9", "#a7f2d3"],   # green/emerald
    4: ["#6b1b1b", "#b02f2f", "#e65a5a", "#f2a7a7"],   # red/ember
}

VECTOR_STYLES = ["icons", "burst", "waves", "mosaic", "orbit"]


def _hex(rgb):
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(c))) for c in rgb)


def _svg_header(w, h, bg):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
            f'viewBox="0 0 {w} {h}">'
            f'<rect width="{w}" height="{h}" fill="{bg}"/>')


def _gen_burst(rnd, w, h, pal):
    cx, cy = w / 2, h / 2
    n = rnd.randint(10, 18)
    rmax = min(w, h) * 0.42
    parts = []
    for i in range(n):
        a = 2 * math.pi * i / n + rnd.uniform(-0.1, 0.1)
        r = rmax * rnd.uniform(0.5, 1.0)
        x, y = cx + r * math.cos(a), cy + r * math.sin(a)
        rr = rmax * rnd.uniform(0.06, 0.14)
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{rr:.1f}" fill="{rnd.choice(pal[1:])}"/>')
    parts.append(f'<circle cx="{cx}" cy="{cy}" r="{rmax*0.22:.1f}" fill="{pal[-1]}"/>')
    return "".join(parts)


def _gen_waves(rnd, w, h, pal):
    parts = []
    layers = rnd.randint(3, 5)
    for li in range(layers):
        base = h * (0.35 + 0.13 * li)
        amp = h * rnd.uniform(0.05, 0.12)
        step = w / 12
        pts = [f"M0,{h}"]
        x = 0.0
        pts.append(f"L0,{base:.1f}")
        while x <= w:
            pts.append(f"Q{x+step/2:.1f},{base+amp*math.sin(x/step+li):.1f} {x+step:.1f},{base:.1f}")
            x += step
        pts.append(f"L{w},{h} Z")
        parts.append(f'<path d="{" ".join(pts)}" fill="{pal[min(li+1, len(pal)-1)]}" opacity="0.9"/>')
    return "".join(parts)


def _gen_mosaic(rnd, w, h, pal):
    parts = []
    cols = rnd.randint(6, 10)
    cw = w / cols
    rows = max(1, int(h / cw))
    ch = h / rows
    for r in range(rows):
        for c in range(cols):
            if rnd.random() < 0.82:
                parts.append(f'<rect x="{c*cw:.1f}" y="{r*ch:.1f}" width="{cw:.1f}" '
                             f'height="{ch:.1f}" fill="{rnd.choice(pal)}"/>')
    return "".join(parts)


def _gen_orbit(rnd, w, h, pal):
    cx, cy = w / 2, h / 2
    parts = []
    for i in range(rnd.randint(3, 5)):
        r = min(w, h) * (0.12 + 0.11 * i)
        parts.append(f'<circle cx="{cx}" cy="{cy}" r="{r:.1f}" fill="none" '
                     f'stroke="{pal[min(i+1, len(pal)-1)]}" stroke-width="{rnd.uniform(3,8):.1f}"/>')
        a = rnd.uniform(0, 2 * math.pi)
        x, y = cx + r * math.cos(a), cy + r * math.sin(a)
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{rnd.uniform(6,14):.1f}" fill="{pal[-1]}"/>')
    parts.append(f'<circle cx="{cx}" cy="{cy}" r="{min(w,h)*0.05:.1f}" fill="{pal[-1]}"/>')
    return "".join(parts)


def _gen_icons(rnd, w, h, pal):
    """Flat rounded-square badge with a simple geometric glyph — clean icon look."""
    m = min(w, h)
    pad = m * 0.12
    parts = [f'<rect x="{pad:.1f}" y="{pad:.1f}" width="{w-2*pad:.1f}" height="{h-2*pad:.1f}" '
             f'rx="{m*0.12:.1f}" fill="{pal[1]}"/>']
    cx, cy = w / 2, h / 2
    glyph = rnd.choice(["tri", "ring", "bars", "plus"])
    fg = pal[-1]
    if glyph == "tri":
        s = m * 0.22
        parts.append(f'<polygon points="{cx:.1f},{cy-s:.1f} {cx+s:.1f},{cy+s:.1f} {cx-s:.1f},{cy+s:.1f}" fill="{fg}"/>')
    elif glyph == "ring":
        parts.append(f'<circle cx="{cx}" cy="{cy}" r="{m*0.22:.1f}" fill="none" stroke="{fg}" stroke-width="{m*0.07:.1f}"/>')
    elif glyph == "bars":
        for k in range(3):
            bh = m * (0.12 + 0.08 * k)
            parts.append(f'<rect x="{cx-m*0.22+k*m*0.16:.1f}" y="{cy+m*0.18-bh:.1f}" '
                         f'width="{m*0.1:.1f}" height="{bh:.1f}" rx="3" fill="{fg}"/>')
    else:  # plus
        t = m * 0.08
        parts.append(f'<rect x="{cx-t/2:.1f}" y="{cy-m*0.22:.1f}" width="{t:.1f}" height="{m*0.44:.1f}" rx="4" fill="{fg}"/>')
        parts.append(f'<rect x="{cx-m*0.22:.1f}" y="{cy-t/2:.1f}" width="{m*0.44:.1f}" height="{t:.1f}" rx="4" fill="{fg}"/>')
    return "".join(parts)


_GENERATORS = {
    "icons": _gen_icons, "burst": _gen_burst, "waves": _gen_waves,
    "mosaic": _gen_mosaic, "orbit": _gen_orbit,
}


def build_svg(style: str, seed: int, w: int = 2000, h: int = 2000) -> str:
    """Return a complete original flat-vector SVG string, deterministic by seed."""
    if style not in _GENERATORS:
        raise ValueError(f"unknown vector style {style!r} (allowed: {VECTOR_STYLES})")
    rnd = random.Random(seed)
    pal = PALETTES[seed % 5]
    bg = pal[0]
    body = _GENERATORS[style](rnd, w, h, pal)
    return _svg_header(w, h, bg) + body + "</svg>"


def svg_to_eps(svg: str, out_eps: Path) -> Path:
    """Convert an SVG string to EPS via cairosvg's PostScript surface."""
    _ensure_cairo()
    from cairosvg.surface import PSSurface
    buf = io.BytesIO()
    PSSurface.convert(bytestring=svg.encode(), write_to=buf)
    data = buf.getvalue()
    # cairo emits "%!PS-Adobe-3.0"; tag as EPSF so Adobe treats it as encapsulated
    if data[:14] == b"%!PS-Adobe-3.0":
        data = b"%!PS-Adobe-3.0 EPSF-3.0" + data[14:]
    out_eps.write_bytes(data)
    return out_eps


def svg_to_preview_jpg(svg: str, out_jpg: Path, size: int = 1200) -> Path:
    """Rasterize SVG to a JPEG preview (Adobe Stock wants a preview alongside EPS)."""
    _ensure_cairo()
    import cairosvg
    from PIL import Image
    png_bytes = cairosvg.svg2png(bytestring=svg.encode(), output_width=size, output_height=size)
    img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    img.save(out_jpg, "JPEG", quality=92)
    return out_jpg


def render_vector(style: str, seed: int, out_dir: Path, idx: int,
                  w: int = 2000, h: int = 2000) -> dict:
    """Generate one vector asset: writes .svg (master), .eps (upload), _preview.jpg."""
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"vec_{idx:03d}"
    svg = build_svg(style, seed, w, h)
    svg_path = out_dir / f"{stem}.svg"
    svg_path.write_text(svg)
    eps_path = svg_to_eps(svg, out_dir / f"{stem}.eps")
    prev_path = svg_to_preview_jpg(svg, out_dir / f"{stem}_preview.jpg")
    return {
        "file": eps_path.name, "svg": svg_path.name, "preview": prev_path.name,
        "style": style, "seed": seed, "width": w, "height": h,
    }
