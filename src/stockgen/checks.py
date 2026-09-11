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

    return rows
