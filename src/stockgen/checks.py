"""Environment checks for stockgen."""
from __future__ import annotations
import shutil
import subprocess

import requests


def doctor(cfg) -> list[tuple[str, bool, str]]:
    rows = []

    def check(name, ok, detail=""):
        rows.append((name, ok, detail))

    # ffmpeg
    ff = shutil.which("ffmpeg")
    check("ffmpeg", bool(ff), ff or "missing — brew install ffmpeg")

    # node
    node = shutil.which("node")
    ver = ""
    if node:
        try:
            ver = subprocess.run(["node", "--version"], capture_output=True, text=True).stdout.strip()
        except Exception:
            pass
    check("node", bool(node), ver or "missing — install Node.js")

    # puppeteer installed?
    pup = (cfg.root / "node_modules" / "puppeteer").exists()
    check("puppeteer", pup, "installed" if pup else "run: npm install")

    # sketches
    sketches = list(cfg.sketches_dir.glob("*.html"))
    check("sketches", bool(sketches), f"{len(sketches)} found: " +
          ", ".join(s.stem for s in sketches))

    # cairosvg (vector SVG->EPS) — import may need brew libcairo via DYLD
    try:
        import os as _os
        _os.environ.setdefault("DYLD_FALLBACK_LIBRARY_PATH", "/opt/homebrew/lib:/usr/local/lib")
        import cairosvg  # noqa: F401
        check("cairosvg", True, "vector SVG->EPS ready")
    except Exception as e:
        check("cairosvg", False, f"vector export unavailable: {str(e)[:50]}")

    # realesrgan (optional AI image upscaler) — lanczos fallback always works
    resr = shutil.which("realesrgan-ncnn-vulkan")
    check("realesrgan", bool(resr), resr + " (AI upscale)" if resr
          else "optional — using ffmpeg/Pillow lanczos fallback")

    # metadata provider
    prov = cfg.get("metadata.provider", "ollama")
    if prov == "ollama":
        host = cfg.get("metadata.ollama_host", "http://localhost:11434")
        model = cfg.get("metadata.ollama_model", "llama3.2:3b")
        try:
            r = requests.get(f"{host}/api/tags", timeout=5)
            models = [m["name"] for m in r.json().get("models", [])]
            has = any(model in m for m in models)
            check("ollama", has, f"{model} " + ("ready" if has else f"NOT pulled (ollama pull {model})"))
        except Exception:
            check("ollama", False, f"not reachable at {host} (brew services start ollama)")
    else:
        check("metadata", True, f"provider={prov}")

    # Smart AI Vision: check vision model
    vmodel = cfg.get("metadata.vision_model", "moondream")
    auto_desc = cfg.get("metadata.auto_describe", True)
    if auto_desc:
        host = cfg.get("metadata.ollama_host", "http://localhost:11434")
        try:
            r = requests.get(f"{host}/api/tags", timeout=5)
            models = [m["name"] for m in r.json().get("models", [])]
            v_has = any(vmodel.split(":")[0] in m for m in models)
            check("vision", v_has, f"{vmodel} " + ("ready — deep visual reading" if v_has else f"NOT pulled (ollama pull {vmodel})"))
        except Exception:
            check("vision", False, f"not reachable at {host} (for auto-describe)")
    else:
        check("vision", True, "auto_describe=off (manual desc only)")

    # SEO keyword config
    kw = cfg.get("metadata.keywords_count", 42)
    check("seo", 30 <= kw <= 49, f"{kw} keywords/asset (target 30-50) — {'✓ in range' if 30 <= kw <= 49 else '⚠ out of 30-50 range'}")

    # CSV export mode
    check("csv", True, "metadata tidak tertanam — file asli aman, CSV terpisah untuk upload massal")

    return rows
