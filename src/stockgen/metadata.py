"""Generate Adobe Stock CSV metadata for rendered clips.

Adobe Stock bulk CSV columns (official):
  Filename, Title, Keywords, Category, Releases
- Title: descriptive, <= 200 chars, no keyword stuffing
- Keywords: comma-separated, up to 49 (order = relevance)
- Category: numeric Adobe Stock category id
- Releases: blank for generated content (no model/property release needed)

Provider: ollama (local llama3.2:3b) | groq | rule (deterministic fallback).
"""
from __future__ import annotations
import csv
import json
import os
import re
from pathlib import Path

import requests

# generator brand names forbidden in Adobe Stock titles/keywords for AI content.
# (Adobe rejects metadata naming the AI tool used.)
FORBIDDEN_WORDS = {
    "veo", "googleflow", "google flow", "flow", "midjourney", "dalle", "dall-e",
    "dall·e", "stable diffusion", "stablediffusion", "sora", "runway", "kling",
    "firefly", "imagen", "gemini", "chatgpt", "openai", "leonardo", "ideogram",
    "pika", "luma", "gen-3", "gen3", "wan", "flux", "sdxl", "ai", "aigenerated",
    "ai-generated", "ai generated",
}

# per-kind vocabulary appended to titles/keywords so image & vector read right.
KIND_VOCAB = {
    "video":  ([], ["4k", "uhd", "motion", "loop", "seamless", "footage", "animation"]),
    "image":  ([], ["high resolution", "background", "graphic", "digital", "wallpaper"]),
    "vector": (["vector illustration"],
               ["vector", "eps", "svg", "flat", "illustration", "icon", "scalable", "graphic"]),
}


# sketch -> base descriptive vocabulary (seeds the LLM + rule fallback)
SKETCH_DESC = {
    "particles": ("abstract flowing particle motion background",
                  ["particles", "flow", "motion", "abstract", "background", "energy",
                   "digital", "dynamic", "loop", "seamless", "technology", "glow"]),
    "gradient":  ("smooth flowing gradient color background",
                  ["gradient", "color", "smooth", "flow", "abstract", "background",
                   "soft", "blend", "loop", "seamless", "calm", "wallpaper"]),
    "waves":     ("layered sine wave abstract landscape motion",
                  ["waves", "wave", "abstract", "motion", "background", "flow",
                   "curve", "loop", "seamless", "rhythm", "blue", "digital"]),
    "nebula":    ("cinematic bokeh light nebula loop background",
                  ["nebula", "bokeh", "light", "cinematic", "space", "glow",
                   "abstract", "background", "loop", "seamless", "dreamy", "cosmic"]),
    "data":      ("animated abstract data visualization shapes",
                  ["data", "visualization", "abstract", "shapes", "motion", "tech",
                   "digital", "background", "loop", "seamless", "network", "graphic"]),
}

PALETTE_WORDS = {
    0: ["blue", "ocean", "cool"], 1: ["violet", "purple", "nebula"],
    2: ["gold", "warm", "amber"], 3: ["green", "emerald", "nature"],
    4: ["red", "ember", "fire"],
}


def _ollama(cfg, prompt: str) -> str | None:
    host = cfg.get("metadata.ollama_host", "http://localhost:11434")
    model = cfg.get("metadata.ollama_model", "llama3.2:3b")
    try:
        r = requests.post(f"{host}/api/generate",
                          json={"model": model, "prompt": prompt, "stream": False,
                                "options": {"temperature": 0.4}},
                          timeout=120)
        r.raise_for_status()
        return r.json().get("response", "").strip()
    except Exception as e:
        print(f"  ollama failed: {e}")
        return None


def _gen_llm(cfg, clip: dict) -> tuple[str, list[str]] | None:
    base_desc, base_kw = SKETCH_DESC.get(clip["sketch"], ("abstract motion background", []))
    pal = PALETTE_WORDS.get(clip["seed"] % 5, [])
    n = cfg.get("metadata.keywords_count", 25)
    prompt = (
        f"You write Adobe Stock metadata for a royalty-free 4K motion background video.\n"
        f"The clip is: {base_desc}. Dominant colors/mood: {', '.join(pal)}.\n"
        f"Return STRICT JSON only:\n"
        f'{{"title":"<descriptive title, 8-15 words, no hashtags>",'
        f'"keywords":["<{n} SHORT search terms>"]}}\n'
        f"Keyword rules: each keyword is ONE word (or at most two), lowercase, "
        f"NO full phrases or sentences. Most relevant first. Aim for {n} keywords.\n"
        f"Base vocabulary to draw from: {', '.join(base_kw + pal)}"
    )
    out = _ollama(cfg, prompt)
    if not out:
        return None
    # tolerant JSON extraction
    try:
        s = out[out.index("{"): out.rindex("}") + 1]
        data = json.loads(s)
        title = str(data.get("title", "")).strip().strip('"')
        raw = [str(k) for k in data.get("keywords", []) if str(k).strip()]
        kws = _normalize_keywords(raw, base_kw + pal, n)
        if title and kws:
            return title, kws
    except Exception:
        pass
    return None


_STOP = {"the", "a", "an", "of", "and", "with", "in", "on", "for", "to", "loop"}


def _normalize_keywords(raw: list[str], backfill: list[str], n: int) -> list[str]:
    """Split multi-word phrases into single terms, dedupe, keep order, backfill to n."""
    out: list[str] = []

    def add(term: str):
        term = term.strip().lower().strip(".,")
        if term and term not in _STOP and term not in out:
            out.append(term)

    for k in raw:
        words = k.strip().lower().replace(",", " ").split()
        if len(words) <= 2:
            add(k)                      # keep short terms (incl. good two-word ones)
        else:
            for w in words:             # explode long phrases into single words
                add(w)
    for b in backfill:                  # ensure we reach the target count
        if len(out) >= n:
            break
        add(b)
    return out[:n]


def _gen_rule(cfg, clip: dict) -> tuple[str, list[str]]:
    base_desc, base_kw = SKETCH_DESC.get(clip["sketch"], ("abstract motion background", []))
    pal = PALETTE_WORDS.get(clip["seed"] % 5, [])
    n = cfg.get("metadata.keywords_count", 25)
    color = pal[0] if pal else "abstract"
    title = f"{color.capitalize()} {base_desc} — seamless 4K loop"
    kws = []
    for k in base_kw + pal + ["4k", "uhd", "animation", "backdrop", "creative",
                              "modern", "smooth", "vibrant", "screensaver", "vj"]:
        if k not in kws:
            kws.append(k)
    return title, kws[:n]


def _strip_forbidden(title: str, kws: list[str]) -> tuple[str, list[str]]:
    """Remove generator brand names (Adobe forbids naming AI tools in metadata)."""
    # title: drop forbidden tokens word-wise
    def clean_title(s: str) -> str:
        low = s.lower()
        for w in sorted(FORBIDDEN_WORDS, key=len, reverse=True):
            low2 = re.sub(rf"(?<![\w-]){re.escape(w)}(?![\w-])", " ", low)
            if low2 != low:
                # rebuild original-case string by removing same spans (case-insensitive)
                s = re.sub(rf"(?i)(?<![\w-]){re.escape(w)}(?![\w-])", " ", s)
                low = low2
        return re.sub(r"\s{2,}", " ", s).strip(" -—,")

    clean_kws = [k for k in kws if k.strip().lower() not in FORBIDDEN_WORDS]
    return clean_title(title), clean_kws


def gen_for_clip(cfg, clip: dict) -> dict:
    provider = cfg.get("metadata.provider", "ollama")
    kind = clip.get("kind", "video")
    is_ai = bool(clip.get("is_ai", False))
    res = None
    if provider in ("ollama", "groq"):
        res = _gen_llm(cfg, clip)
    if not res:
        res = _gen_rule(cfg, clip)   # always succeeds
    title, kws = res

    # apply per-kind vocabulary (image/vector need their own descriptors)
    kv_title, kv_kws = KIND_VOCAB.get(kind, ([], []))
    n = cfg.get("metadata.keywords_count", None) or (49 if kind == "vector" else 25)
    # kind vocab is PREPENDED (most relevant first) so it survives truncation
    merged: list[str] = []
    for k in kv_kws + kws:
        if k not in merged:
            merged.append(k)
    kws = merged
    # drop video-only descriptors that make no sense on stills/vectors
    if kind in ("image", "vector"):
        kws = [k for k in kws if k not in {"4k", "uhd", "loop", "seamless", "motion",
                                           "animation", "footage", "screensaver", "vj"}]
        # strip motion-loop phrasing from titles of still assets
        title = re.sub(r"\s*—\s*seamless 4K loop", "", title, flags=re.I).strip()
    if kv_title and kind == "vector" and "vector" not in title.lower():
        title = f"{title} — {kv_title[0]}"
    kws = kws[:n]

    # AI content: strip generator brand names from metadata (Adobe rule)
    if is_ai:
        title, kws = _strip_forbidden(title, kws)

    return {
        "Filename": clip.get("file") or clip.get("Filename"),
        "Title": title,
        "Keywords": ", ".join(kws),
        "Category": cfg.get("metadata.default_category", 8),
        "Releases": "",
    }


def write_csv(rows: list[dict], out_csv: Path) -> Path:
    cols = ["Filename", "Title", "Keywords", "Category", "Releases"]
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return out_csv


def gen_for_asset(cfg, asset) -> dict:
    """Build a metadata row from an assets.Asset (registry-driven, kind/AI aware)."""
    clip = {
        "file": asset.file,
        "kind": asset.kind,
        "is_ai": asset.is_ai,
        "sketch": asset.sketch or "particles",
        "seed": asset.seed or 0,
    }
    return gen_for_clip(cfg, clip)


def build_per_kind_csvs(cfg, registry, batch_dir: Path) -> dict[str, Path]:
    """Generate one Adobe Stock CSV per asset kind present in the registry.

    Only SELLABLE assets are written; blocked (download) assets are skipped and
    must have already been rejected upstream. Returns {kind: csv_path}.
    """
    written: dict[str, Path] = {}
    by_kind: dict[str, list] = {}
    for a in registry.sellable():
        by_kind.setdefault(a.kind, []).append(a)
    for kind, items in by_kind.items():
        rows = [gen_for_asset(cfg, a) for a in items]
        out = batch_dir / f"metadata_{kind}.csv"
        write_csv(rows, out)
        written[kind] = out
    return written
