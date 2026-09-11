"""Upscale video/image to 4K — for the user's OWN assets only.

GUARDRAIL: only assets whose source is sellable (original | ai_googleflow) may be
upscaled here. Upscaling downloaded stock (Pexels/Pixabay/internet) and selling
it is infringement, so source=download is refused.

Free backend: ffmpeg `scale` with the lanczos filter (high-quality resampling,
no GPU needed). If `realesrgan-ncnn-vulkan` is on PATH it is preferred for images
(sharper AI upscsale); video always uses ffmpeg lanczos.
"""
from __future__ import annotations
import json
import shutil
import subprocess
from pathlib import Path

from PIL import Image

from . import assets as assets_mod

TARGETS = {"4k": (3840, 2160), "4k_v": (2160, 3840)}


def _probe_dims(path: Path) -> tuple[int, int]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "json", str(path)],
        check=True, capture_output=True, text=True,
    ).stdout
    st = (json.loads(out).get("streams") or [{}])[0]
    return int(st.get("width") or 0), int(st.get("height") or 0)


def _target_for(w: int, h: int, to: str) -> tuple[int, int]:
    """Pick a 4K target that preserves the input orientation."""
    if to != "4k":
        return TARGETS[to]
    return TARGETS["4k_v"] if h > w else TARGETS["4k"]


def _assert_source_ok(source: str) -> None:
    if source == assets_mod.SOURCE_DOWNLOAD:
        raise assets_mod.GuardrailError(
            "refusing to upscale source=download: upscaling downloaded stock for "
            "resale is copyright infringement."
        )
    if source not in assets_mod.SELLABLE_SOURCES:
        raise assets_mod.GuardrailError(
            f"refusing to upscale unsellable source {source!r} "
            f"(allowed: {sorted(assets_mod.SELLABLE_SOURCES)})"
        )


def upscale_video(src: Path, out: Path, to: str = "4k") -> dict:
    """Upscale a video to 4K via ffmpeg lanczos (H.264, yuv420p, high quality).

    WARNING: Adobe Stock FORBIDS up-res (HD->4K): "Submit footage as shot".
    Up-resed files trigger Adobe's low-quality warning. Only use this for
    non-Adobe purposes, or when down-converting from >4K sources.
    For Adobe, use prepare_native_video() instead.
    """
    w, h = _probe_dims(src)
    tw, th = _target_for(w, h, to)
    out.parent.mkdir(parents=True, exist_ok=True)
    vf = (f"scale={tw}:{th}:flags=lanczos:force_original_aspect_ratio=decrease,"
          f"pad={tw}:{th}:(ow-iw)/2:(oh-ih)/2,setsar=1")
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(src), "-vf", vf,
         "-c:v", "libx264", "-preset", "slow", "-crf", "16",
         "-pix_fmt", "yuv420p", "-movflags", "+faststart",
         "-c:a", "copy", str(out)],
        check=True, capture_output=True, text=True,
    )
    return {"file": out.name, "from": f"{w}x{h}", "to": f"{tw}x{th}",
            "aspect": "9:16" if th > tw else "16:9"}


def _has_audio(path: Path) -> bool:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a:0",
             "-show_entries", "stream=index", "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=60).stdout.strip()
        return bool(out)
    except Exception:
        return False


def prepare_native_video(src: Path, out: Path) -> dict:
    """Re-encode a video at its NATIVE resolution for Adobe Stock submission.

    Adobe forbids up-res, so the compliant path is: keep native frame size,
    high-quality H.264 (CRF 14, slow), yuv420p, faststart, audio kept at 48kHz.
    Native 1920x1080 is a fully accepted Adobe resolution (min 1080 both sides).
    """
    w, h = _probe_dims(src)
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-i", str(src),
           "-c:v", "libx264", "-preset", "slow", "-crf", "14",
           "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
    if _has_audio(src):
        cmd += ["-c:a", "aac", "-b:a", "320k", "-ar", "48000"]
    cmd.append(str(out))
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    nw, nh = _probe_dims(out)
    return {"file": out.name, "from": f"{w}x{h}", "to": f"{nw}x{nh}",
            "aspect": "9:16" if nh > nw else "16:9", "native": True}


def _realesrgan_bin() -> str | None:
    return shutil.which("realesrgan-ncnn-vulkan")


def _realesrgan_upscale(src: Path, tmp_out: Path, model: str = "realesrgan-x4plus") -> bool:
    """Run realesrgan (x4) to tmp_out. Returns True on success, False to fall back."""
    exe = _realesrgan_bin()
    if not exe:
        return False
    try:
        subprocess.run([exe, "-i", str(src), "-o", str(tmp_out), "-n", model],
                       check=True, capture_output=True, text=True)
        return tmp_out.exists()
    except Exception:
        return False


def upscale_image(src: Path, out: Path, to: str = "4k") -> dict:
    """Upscale an image to 4K. Uses realesrgan (x4, GPU) if available, else Pillow lanczos."""
    with Image.open(src) as im:
        im.load()
        w, h = im.size
    tw, th = _target_for(w, h, to)
    out.parent.mkdir(parents=True, exist_ok=True)

    # 1) optional AI upscale (realesrgan x4) into a temp PNG for sharper detail
    ai_src = src
    tmp = out.with_name(f".{out.stem}_x4.png")
    used_ai = _realesrgan_upscale(src, tmp)
    if used_ai:
        ai_src = tmp

    # 2) fit to the 4K target (upscale-only) with Pillow lanczos
    with Image.open(ai_src) as im2:
        im2 = im2.convert("RGB")
        scale = min(tw / im2.size[0], th / im2.size[1])
        if scale != 1:
            im2 = im2.resize((max(1, round(im2.size[0] * scale)),
                              max(1, round(im2.size[1] * scale))), Image.LANCZOS)
        fmt = "JPEG" if out.suffix.lower() in (".jpg", ".jpeg") else out.suffix.lstrip(".").upper()
        if fmt == "JPEG":
            im2.save(out, fmt, quality=92, subsampling=0)
        else:
            im2.save(out, fmt)
        final = im2.size
    if tmp.exists():
        tmp.unlink()
    return {"file": out.name, "from": f"{w}x{h}", "to": f"{final[0]}x{final[1]}",
            "engine": "realesrgan+lanczos" if used_ai else "lanczos"}


def upscale_asset(asset, batch: Path, to: str = "4k") -> dict:
    """Upscale a registry asset in place-adjacent (writes <stem>_4k.<ext>)."""
    _assert_source_ok(asset.source)
    src = batch / asset.file
    if not src.exists():
        raise FileNotFoundError(f"asset file missing: {src}")
    stem = src.stem
    out = src.with_name(f"{stem}_4k{src.suffix}")
    if asset.kind == assets_mod.KIND_VIDEO:
        info = upscale_video(src, out, to)
    elif asset.kind == assets_mod.KIND_IMAGE:
        info = upscale_image(src, out, to)
    else:
        raise ValueError(f"cannot upscale kind={asset.kind!r} (video/image only)")
    return info
