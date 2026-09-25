"""Adobe Stock submission QC — pre-submit checks for stockgen assets + CSVs.

Catches the rejection reasons actually hit at Adobe QC BEFORE upload:

  - up-resed video (Adobe forbids HD->4K up-res; native frame size must match
    the encoded size — an upscaled 1080p->4K clip trips the "up-res" warning)
  - video below 720p floor (Adobe accepts 720p+, 1080p and 4K recommended)
  - image below 4.0 MP floor (Adobe strictly requires >=4MP for raster stills)
  - vector missing EPS or preview JPEG
  - keyword count > 49 (Adobe hard limit is 49; target 30-49)
  - duplicate keywords
  - title > 200 chars or empty
  - generator brand names leaking into metadata of AI assets (veo, midjourney, etc.)
  - missing files (registry points at a deleted/unlinked file)

Usage:
    from . import qc
    report = qc.qc_batch(cfg, registry, batch_dir)   # -> {"ok": bool, "items": [...]}
    qc.print_report(report)                          # rich console output
"""
from __future__ import annotations
import re
import subprocess
import json
from pathlib import Path

from . import assets as assets_mod
from . import metadata as meta_mod

ADOBE_MAX_KEYWORDS = 49
ADOBE_RECOMMENDED_MIN_KEYWORDS = 25     # Adobe wants meaningful coverage; <25 = weak ranking
ADOBE_MAX_TITLE = 200
VIDEO_MIN_MEGAPIXELS = 0.9              # 720p floor (1280x720 = 0.92MP)
IMAGE_MIN_MEGAPIXELS = 4.0              # 4MP floor for images

# frame sizes that indicate HD up-resed to 4K (exactly 2x of a common HD size)
UP_RES_SUSPECTS = {
    (1920, 1080): "1080p",
    (1280, 720): "720p",
    (1080, 1920): "vertical 1080p",
    (720, 1280): "vertical 720p",
}

FORBIDDEN_BRANDS = sorted(meta_mod.FORBIDDEN_WORDS, key=len, reverse=True)


def probe_video(path: Path) -> dict | None:
    """ffprobe width/height/duration — None when ffprobe fails/file missing."""
    if not path.exists():
        return None
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height,codec_name",
             "-show_entries", "format=duration",
             "-of", "json", str(path)],
            check=True, capture_output=True, text=True,
        ).stdout
        data = json.loads(out)
        st = (data.get("streams") or [{}])[0]
        return {
            "width": int(st.get("width") or 0),
            "height": int(st.get("height") or 0),
            "duration": float((data.get("format") or {}).get("duration") or 0),
            "codec": st.get("codec_name", ""),
        }
    except Exception:
        return None


def _image_dims(path: Path) -> tuple[int, int] | None:
    try:
        from PIL import Image
        with Image.open(path) as im:
            return im.size
    except Exception:
        return None


def check_asset(asset: assets_mod.Asset, batch_dir: Path) -> list[dict]:
    """Technical checks for ONE asset. Returns list of issues (empty = pass)."""
    issues: list[dict] = []
    path = batch_dir / asset.file
    if not path.exists():
        issues.append({"level": "error", "check": "file-exists",
                       "msg": f"{asset.file}: file missing (renamed or deleted?)"})
        return issues

    if asset.kind == assets_mod.KIND_VIDEO:
        p = probe_video(path)
        if not p or p["width"] == 0:
            issues.append({"level": "error", "check": "video-probe",
                           "msg": f"{asset.file}: ffprobe failed"})
            return issues
        mp = (p["width"] * p["height"]) / 1_000_000
        if mp < VIDEO_MIN_MEGAPIXELS:
            issues.append({"level": "error", "check": "video-floor",
                           "msg": f"{asset.file}: {p['width']}x{p['height']} = {mp:.1f}MP "
                                  f"< Adobe 720p (0.9MP) video floor"})
        elif mp < 2.0:
            issues.append({"level": "warn", "check": "video-res-low",
                           "msg": f"{asset.file}: {p['width']}x{p['height']} is 720p — "
                                  f"Adobe recommends 1080p+ for best commercial earnings"})

        # up-res heuristic: encoded size exactly 2x a common HD size AND the
        # registry recorded a smaller native size at render/ingest time.
        nat = (asset.width, asset.height) if asset.width and asset.height else None
        if nat and nat in UP_RES_SUSPECTS:
            enc = (p["width"], p["height"])
            if enc == (nat[0] * 2, nat[1] * 2):
                issues.append({"level": "error", "check": "up-res",
                               "msg": f"{asset.file}: looks like {UP_RES_SUSPECTS[nat]} "
                                      f"up-resed to {p['width']}x{p['height']} — Adobe forbids "
                                      f"HD->4K up-res. Submit native ({nat[0]}x{nat[1]}) via "
                                      f"'Prepare native' instead."})
        elif nat and (p["width"], p["height"]) != nat:
            issues.append({"level": "warn", "check": "res-mismatch",
                           "msg": f"{asset.file}: encoded {p['width']}x{p['height']} != "
                                  f"registered native {nat[0]}x{nat[1]} (re-encoded?)"})

    if asset.kind == assets_mod.KIND_IMAGE:
        dims = _image_dims(path)
        if dims:
            mp = (dims[0] * dims[1]) / 1_000_000
            if mp < IMAGE_MIN_MEGAPIXELS:
                issues.append({"level": "error", "check": "image-4mp",
                               "msg": f"{asset.file}: {dims[0]}x{dims[1]} = {mp:.1f}MP "
                                      f"< Adobe 4MP image floor"})

    if asset.kind == assets_mod.KIND_VECTOR:
        if path.suffix.lower() == ".eps":
            prev = path.with_name(path.stem + "_preview.jpg")
            if not prev.exists():
                issues.append({"level": "warn", "check": "vector-preview",
                               "msg": f"{asset.file}: missing preview JPEG ({prev.name}) — "
                                      f"Adobe requires preview JPEG alongside EPS"})
        elif path.suffix.lower() == ".svg":
            eps = path.with_suffix(".eps")
            if not eps.exists():
                issues.append({"level": "warn", "check": "vector-eps",
                               "msg": f"{asset.file}: missing .eps export — "
                                      f"Adobe requires EPS for vector submissions"})
    return issues


def check_row(row: dict, is_ai: bool) -> list[dict]:
    """Adobe metadata checks for ONE CSV row."""
    issues: list[dict] = []
    fname = row.get("Filename", "")
    title = (row.get("Title") or "").strip()
    kws_raw = row.get("Keywords") or ""
    kws = [k.strip().lower() for k in kws_raw.split(",") if k.strip()]

    if not fname:
        issues.append({"level": "error", "check": "csv-filename",
                       "msg": "row with empty Filename"})
    if len(title) > ADOBE_MAX_TITLE:
        issues.append({"level": "error", "check": "title-length",
                       "msg": f"{fname}: title {len(title)} chars > {ADOBE_MAX_TITLE}"})
    words = len(title.split())
    if words < 5:
        issues.append({"level": "warn", "check": "title-words",
                       "msg": f"{fname}: title only {words} words (8+ words recommended)"})
    if len(kws) > ADOBE_MAX_KEYWORDS:
        issues.append({"level": "error", "check": "keyword-count",
                       "msg": f"{fname}: {len(kws)} keywords > Adobe max {ADOBE_MAX_KEYWORDS}"})
    elif len(kws) < ADOBE_RECOMMENDED_MIN_KEYWORDS:
        issues.append({"level": "warn", "check": "keyword-count",
                       "msg": f"{fname}: only {len(kws)} keywords (recommend {ADOBE_RECOMMENDED_MIN_KEYWORDS}-{ADOBE_MAX_KEYWORDS})"})
    dupes = sorted({k for k in kws if kws.count(k) > 1})
    if dupes:
        issues.append({"level": "error", "check": "keyword-dupes",
                       "msg": f"{fname}: duplicate keywords: {', '.join(dupes[:5])}"})
    if is_ai:
        blob = " | ".join([title.lower()] + kws)
        for brand in FORBIDDEN_BRANDS:
            if re.search(rf"(?<![\w-]){re.escape(brand)}(?![\w-])", blob):
                issues.append({"level": "error", "check": "ai-brand",
                               "msg": f"{fname}: AI asset metadata names generator brand "
                                      f"{brand!r} — Adobe forbids it"})
                break
    return issues


def qc_batch(cfg, registry, batch_dir: Path, rows: list[dict] | None = None) -> dict:
    """Full QC pass over a batch: asset technicals + CSV rows (if provided).

    rows = output of gen_for_asset() / CSV rows for the sellable assets,
    aligned by Filename == asset.file. When None, metadata checks are skipped.
    """
    items: list[dict] = []
    for a in registry.sellable():
        issues = check_asset(a, batch_dir)
        if rows is not None:
            match = next((r for r in rows if r.get("Filename") == a.file), None)
            if match is None:
                issues.append({"level": "error", "check": "csv-missing",
                               "msg": f"{a.file}: no CSV row generated"})
            else:
                issues += check_row(match, is_ai=a.is_ai)
        items.append({"file": a.file, "kind": a.kind, "issues": issues})
    blocked = [a.file for a in registry.blocked()]
    has_errors = any(any(i["level"] == "error" for i in item["issues"]) for item in items)
    ok = not has_errors and not blocked
    return {"ok": ok, "items": items, "blocked": blocked}


def print_report(report: dict) -> bool:
    """Pretty-print a qc_batch report. Returns True when no blocking errors exist."""
    from rich.console import Console
    from rich.table import Table
    console = Console()
    t = Table(title="Adobe Stock QC (pre-submit)")
    t.add_column("File"); t.add_column("Kind"); t.add_column("QC")
    has_errors = False
    for item in report["items"]:
        errors = [i for i in item["issues"] if i["level"] == "error"]
        warns = [i for i in item["issues"] if i["level"] == "warn"]
        if errors:
            has_errors = True
            t.add_row(item["file"], item["kind"], f"[red]✗ {errors[0]['msg']}[/]")
        elif warns:
            t.add_row(item["file"], item["kind"], f"[yellow]! {warns[0]['msg']}[/]")
        else:
            t.add_row(item["file"], item["kind"], "[green]✓ pass[/]")
    console.print(t)
    for item in report["items"]:
        # print remaining issues as sub-bullets
        all_iss = item["issues"]
        if len(all_iss) > 1:
            for extra in all_iss[1:]:
                color = "red" if extra["level"] == "error" else "yellow"
                console.print(f"  [{color}]•[/] {extra['msg']}")
    if report["blocked"]:
        console.print(f"[red]✗ {len(report['blocked'])} BLOCKED asset(s) in registry — "
                      f"remove them before export.[/]")
        return False
    if has_errors:
        console.print("[red]✗ QC failed — resolve the errors above before uploading to Adobe Stock.[/]")
        return False
    console.print("[green]✓ QC passed — all assets compliant with Adobe Stock specifications.[/]")
    return True
