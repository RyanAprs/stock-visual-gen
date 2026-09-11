"""Config + env loading for stockgen."""
from __future__ import annotations
import os
from pathlib import Path

import yaml
from dotenv import load_dotenv


class Config:
    def __init__(self, raw: dict, root: Path):
        self.raw = raw
        self.root = root

    @classmethod
    def load(cls, path: str | None = None) -> "Config":
        root = Path(__file__).resolve().parents[2]
        load_dotenv(root / ".env")
        cfg_path = Path(path) if path else root / "config.yaml"
        raw = yaml.safe_load(cfg_path.read_text()) if cfg_path.exists() else {}
        return cls(raw or {}, root)

    def get(self, dotted: str, default=None):
        cur = self.raw
        for part in dotted.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                return default
        return cur

    @property
    def cache_dir(self) -> Path:
        d = self.root / "cache"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def output_dir(self) -> Path:
        d = self.root / "output"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def sketches_dir(self) -> Path:
        return self.root / self.get("render.sketches_dir", "sketches")

    def dims(self, aspect: str | None = None) -> tuple[int, int]:
        """Return (w,h). aspect '16:9' (landscape) or '9:16' (vertical/shorts)."""
        res = str(self.get("resolution", "3840x2160"))
        w, h = res.lower().split("x")
        w, h = int(w), int(h)
        lo, hi = min(w, h), max(w, h)
        if aspect == "9:16":
            return lo, hi          # vertical
        return hi, lo              # 16:9 landscape (default)
