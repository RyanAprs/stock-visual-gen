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

XMAS_PALETTES = {
    0: ["#0b1f14", "#165b33", "#bb2528", "#f8b229", "#ffffff"],  # forest, pine, ruby, gold, snow
    1: ["#150c1b", "#1a4d36", "#c72626", "#ffd166", "#f4f8fb"],  # deep night, pine, red berry, gold, ice
    2: ["#09182b", "#1e3f66", "#d9383a", "#fbb03b", "#eef7ff"],  # winter navy, pine, crimson, star, frost
    3: ["#142416", "#216835", "#b91c1c", "#fbbf24", "#fef3c7"],  # evergreen, wreath red, gold glow, ivory
    4: ["#121820", "#15803d", "#dc2626", "#f59e0b", "#fafafa"],  # dark slate, holly, bright red, amber, white
}

VECTOR_STYLES = ["icons", "burst", "waves", "mosaic", "orbit", "xmas"]


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


def _star_points(cx: float, cy: float, r_out: float, r_in: float, points: int = 5) -> str:
    pts = []
    step = math.pi / points
    for i in range(2 * points):
        r = r_out if i % 2 == 0 else r_in
        angle = i * step - math.pi / 2
        pts.append(f"{cx + r * math.cos(angle):.1f},{cy + r * math.sin(angle):.1f}")
    return " ".join(pts)


def _gen_xmas_tree(rnd: random.Random, w: int, h: int, pal: list[str]) -> str:
    parts = []
    cx = w / 2
    # Background festive snow dots
    for _ in range(rnd.randint(35, 60)):
        sx = rnd.uniform(w * 0.05, w * 0.95)
        sy = rnd.uniform(h * 0.05, h * 0.95)
        sr = rnd.uniform(2.0, 5.5)
        op = rnd.uniform(0.3, 0.85)
        parts.append(f'<circle cx="{sx:.1f}" cy="{sy:.1f}" r="{sr:.1f}" fill="{pal[4]}" opacity="{op:.2f}"/>')

    # Tree trunk
    tw = w * 0.10
    th = h * 0.16
    ty = h * 0.76
    parts.append(f'<rect x="{cx - tw/2:.1f}" y="{ty:.1f}" width="{tw:.1f}" height="{th:.1f}" rx="6" fill="#4a2e18"/>')

    # 4 Tiered Pine Layers (bottom to top)
    tiers = [
        (h * 0.55, h * 0.78, w * 0.38),
        (h * 0.42, h * 0.64, w * 0.31),
        (h * 0.30, h * 0.50, w * 0.23),
        (h * 0.18, h * 0.36, w * 0.15),
    ]
    pine_color = pal[1]
    for i, (yp, yb, hw) in enumerate(tiers):
        pts = f"{cx},{yp:.1f} {cx+hw:.1f},{yb:.1f} {cx-hw:.1f},{yb:.1f}"
        parts.append(f'<polygon points="{pts}" fill="{pine_color}"/>')
        # snow trim on bottom edge of tier
        trim_h = h * 0.025
        snow_pts = f"{cx-hw:.1f},{yb:.1f} {cx+hw:.1f},{yb:.1f} {cx+hw*0.9:.1f},{yb+trim_h:.1f} {cx-hw*0.9:.1f},{yb+trim_h:.1f}"
        parts.append(f'<polygon points="{snow_pts}" fill="{pal[4]}" opacity="0.95"/>')

    # Bauble ornaments hanging on tree
    bauble_colors = [pal[2], pal[3], pal[4]]
    for yp, yb, hw in tiers:
        num_b = rnd.randint(3, 5)
        for _ in range(num_b):
            bx = cx + rnd.uniform(-hw * 0.75, hw * 0.75)
            by = rnd.uniform(yp + (yb - yp) * 0.3, yb - h * 0.01)
            br = rnd.uniform(w * 0.018, w * 0.032)
            bcol = rnd.choice(bauble_colors)
            parts.append(f'<circle cx="{bx:.1f}" cy="{by:.1f}" r="{br:.1f}" fill="{bcol}"/>')
            parts.append(f'<circle cx="{bx-br*0.3:.1f}" cy="{by-br*0.3:.1f}" r="{br*0.35:.1f}" fill="#ffffff" opacity="0.65"/>')

    # Star topper on the top peak
    star_y = tiers[-1][0]
    star_pts = _star_points(cx, star_y, w * 0.07, w * 0.028, points=5)
    parts.append(f'<polygon points="{star_pts}" fill="{pal[3]}"/>')
    parts.append(f'<circle cx="{cx}" cy="{star_y}" r="{w*0.015:.1f}" fill="#ffffff" opacity="0.8"/>')
    return "".join(parts)


def _gen_xmas_snowflake(rnd: random.Random, w: int, h: int, pal: list[str]) -> str:
    cx, cy = w / 2, h / 2
    r_max = min(w, h) * 0.38
    parts = []

    parts.append(f'<circle cx="{cx}" cy="{cy}" r="{r_max * 1.05:.1f}" fill="none" stroke="{pal[3]}" stroke-width="2" opacity="0.25"/>')
    parts.append(f'<circle cx="{cx}" cy="{cy}" r="{r_max * 0.55:.1f}" fill="none" stroke="{pal[4]}" stroke-width="3" opacity="0.4"/>')

    arm_parts = []
    arm_parts.append(f'<line x1="0" y1="0" x2="0" y2="{-r_max:.1f}" stroke="{pal[4]}" stroke-width="{w*0.018:.1f}" stroke-linecap="round"/>')

    branch_specs = [
        (0.40, w * 0.11, 40),
        (0.65, w * 0.08, 45),
        (0.85, w * 0.05, 50),
    ]
    for pos_pct, blen, ang_deg in branch_specs:
        by = -r_max * pos_pct
        ang = math.radians(ang_deg)
        dx = blen * math.sin(ang)
        dy = blen * math.cos(ang)
        arm_parts.append(f'<line x1="0" y1="{by:.1f}" x2="{-dx:.1f}" y2="{by-dy:.1f}" stroke="{pal[4]}" stroke-width="{w*0.013:.1f}" stroke-linecap="round"/>')
        arm_parts.append(f'<line x1="0" y1="{by:.1f}" x2="{dx:.1f}" y2="{by-dy:.1f}" stroke="{pal[4]}" stroke-width="{w*0.013:.1f}" stroke-linecap="round"/>')
        arm_parts.append(f'<circle cx="{-dx:.1f}" cy="{by-dy:.1f}" r="{w*0.008:.1f}" fill="{pal[3]}"/>')
        arm_parts.append(f'<circle cx="{dx:.1f}" cy="{by-dy:.1f}" r="{w*0.008:.1f}" fill="{pal[3]}"/>')

    tip_y = -r_max
    tip_d = w * 0.025
    tip_pts = f"0,{tip_y-tip_d:.1f} {tip_d*0.7:.1f},{tip_y:.1f} 0,{tip_y+tip_d:.1f} {-tip_d*0.7:.1f},{tip_y:.1f}"
    arm_parts.append(f'<polygon points="{tip_pts}" fill="{pal[3]}"/>')

    arm_svg = "".join(arm_parts)
    for i in range(6):
        deg = i * 60
        parts.append(f'<g transform="translate({cx},{cy}) rotate({deg})">{arm_svg}</g>')

    hex_pts = []
    r_hex = r_max * 0.22
    for i in range(6):
        a = i * math.pi / 3
        hex_pts.append(f"{cx + r_hex*math.cos(a):.1f},{cy + r_hex*math.sin(a):.1f}")
    parts.append(f'<polygon points="{" ".join(hex_pts)}" fill="none" stroke="{pal[3]}" stroke-width="{w*0.012:.1f}"/>')

    center_star = _star_points(cx, cy, r_max * 0.16, r_max * 0.08, points=6)
    parts.append(f'<polygon points="{center_star}" fill="{pal[4]}"/>')
    parts.append(f'<circle cx="{cx}" cy="{cy}" r="{r_max*0.05:.1f}" fill="{pal[3]}"/>')

    for _ in range(24):
        fx = cx + rnd.uniform(-w*0.44, w*0.44)
        fy = cy + rnd.uniform(-h*0.44, h*0.44)
        if math.hypot(fx - cx, fy - cy) > r_max * 0.4:
            fr = rnd.uniform(2.5, 6.0)
            parts.append(f'<circle cx="{fx:.1f}" cy="{fy:.1f}" r="{fr:.1f}" fill="{pal[4]}" opacity="{rnd.uniform(0.3, 0.8):.2f}"/>')

    return "".join(parts)


def _gen_xmas_bauble(rnd: random.Random, w: int, h: int, pal: list[str]) -> str:
    cx = w / 2
    cy = h * 0.54
    r_sphere = min(w, h) * 0.32
    parts = []

    cap_top = cy - r_sphere - h * 0.05
    parts.append(f'<line x1="{cx}" y1="0" x2="{cx}" y2="{cap_top:.1f}" stroke="{pal[3]}" stroke-width="4"/>')
    ring_r = h * 0.025
    parts.append(f'<circle cx="{cx}" cy="{cap_top:.1f}" r="{ring_r:.1f}" fill="none" stroke="{pal[3]}" stroke-width="5"/>')

    cap_w = r_sphere * 0.38
    cap_h = h * 0.04
    parts.append(f'<rect x="{cx - cap_w/2:.1f}" y="{cy - r_sphere - cap_h*0.8:.1f}" width="{cap_w:.1f}" height="{cap_h:.1f}" rx="4" fill="{pal[3]}"/>')

    base_color = pal[2]
    parts.append(f'<circle cx="{cx}" cy="{cy}" r="{r_sphere:.1f}" fill="{base_color}"/>')

    steps = 14
    step_w = (r_sphere * 1.7) / steps
    start_x = cx - (r_sphere * 1.7) / 2
    zz_pts = []
    for i in range(steps + 1):
        zx = start_x + i * step_w
        zy = cy + ((-1) ** i) * (r_sphere * 0.12)
        zz_pts.append(f"{zx:.1f},{zy:.1f}")
    parts.append(f'<polyline points="{" ".join(zz_pts)}" fill="none" stroke="{pal[3]}" stroke-width="{w*0.015:.1f}" stroke-linecap="round" stroke-linejoin="round"/>')

    parts.append(f'<line x1="{cx - r_sphere*0.8:.1f}" y1="{cy - r_sphere*0.28:.1f}" x2="{cx + r_sphere*0.8:.1f}" y2="{cy - r_sphere*0.28:.1f}" stroke="{pal[4]}" stroke-width="{w*0.01:.1f}" stroke-linecap="round"/>')
    parts.append(f'<line x1="{cx - r_sphere*0.8:.1f}" y1="{cy + r_sphere*0.28:.1f}" x2="{cx + r_sphere*0.8:.1f}" y2="{cy + r_sphere*0.28:.1f}" stroke="{pal[4]}" stroke-width="{w*0.01:.1f}" stroke-linecap="round"/>')

    cstar_pts = _star_points(cx, cy, r_sphere * 0.22, r_sphere * 0.09, points=8)
    parts.append(f'<polygon points="{cstar_pts}" fill="{pal[3]}"/>')
    parts.append(f'<circle cx="{cx}" cy="{cy}" r="{r_sphere*0.06:.1f}" fill="{pal[4]}"/>')

    for k in range(-3, 4):
        parts.append(f'<circle cx="{cx + k * r_sphere*0.22:.1f}" cy="{cy - r_sphere*0.42:.1f}" r="{w*0.014:.1f}" fill="{pal[3]}"/>')
        parts.append(f'<circle cx="{cx + k * r_sphere*0.22:.1f}" cy="{cy + r_sphere*0.42:.1f}" r="{w*0.014:.1f}" fill="{pal[4]}"/>')

    gl_x = cx - r_sphere * 0.22
    gl_y = cy - r_sphere * 0.22
    parts.append(f'<ellipse cx="{gl_x:.1f}" cy="{gl_y:.1f}" rx="{r_sphere*0.25:.1f}" ry="{r_sphere*0.14:.1f}" transform="rotate(-35 {gl_x:.1f} {gl_y:.1f})" fill="#ffffff" opacity="0.32"/>')

    for _ in range(18):
        bx = rnd.uniform(w * 0.08, w * 0.92)
        by = rnd.uniform(h * 0.1, h * 0.9)
        if math.hypot(bx - cx, by - cy) > r_sphere * 1.05:
            br = rnd.uniform(w * 0.02, w * 0.07)
            bcol = rnd.choice([pal[3], pal[4], pal[1]])
            parts.append(f'<circle cx="{bx:.1f}" cy="{by:.1f}" r="{br:.1f}" fill="{bcol}" opacity="{rnd.uniform(0.15, 0.4):.2f}"/>')

    return "".join(parts)


def _gen_xmas(rnd: random.Random, w: int, h: int, pal: list[str]) -> str:
    """Parametric Christmas holiday vector: tree, snowflake, or festive bauble."""
    motif = rnd.choice(["tree", "snowflake", "bauble"])
    if motif == "tree":
        return _gen_xmas_tree(rnd, w, h, pal)
    elif motif == "snowflake":
        return _gen_xmas_snowflake(rnd, w, h, pal)
    else:
        return _gen_xmas_bauble(rnd, w, h, pal)


_GENERATORS = {
    "icons": _gen_icons, "burst": _gen_burst, "waves": _gen_waves,
    "mosaic": _gen_mosaic, "orbit": _gen_orbit, "xmas": _gen_xmas,
}


def build_svg(style: str, seed: int, w: int = 2000, h: int = 2000) -> str:
    """Return a complete original flat-vector SVG string, deterministic by seed."""
    if style not in _GENERATORS:
        raise ValueError(f"unknown vector style {style!r} (allowed: {VECTOR_STYLES})")
    rnd = random.Random(seed)
    if style == "xmas":
        pal = XMAS_PALETTES[seed % len(XMAS_PALETTES)]
    else:
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
