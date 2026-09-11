"""Asset registry + IP-source guardrail for stockgen v2.

Central manifest tracking EVERY sellable asset (video / image / vector) across a
batch, tagged with its IP `source`. The guardrail is the core safety mechanism:
Adobe Stock contributors must own/create each asset, so downloaded stock
(Pexels/Pixabay/internet) is HARD-BLOCKED before metadata/export.

source values:
  original       -> made BY stockgen (p5.js render / SVG generator). Sellable.
  ai_googleflow  -> Google Flow/Veo, PAID plan (commercial rights). Sellable*,
                    forces is_ai=True; metadata must strip generator names.
  download        -> Pexels/Pixabay/internet. NOT the user's IP. REJECTED.

Any asset whose source is not in SELLABLE_SOURCES (or is missing) is refused.
"""
from __future__ import annotations
import json
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path

# --- source policy ----------------------------------------------------------

SOURCE_ORIGINAL = "original"
SOURCE_AI_GOOGLEFLOW = "ai_googleflow"
SOURCE_DOWNLOAD = "download"

# sources legal to sell on Adobe Stock
SELLABLE_SOURCES = {SOURCE_ORIGINAL, SOURCE_AI_GOOGLEFLOW}
# sources that force the is_ai flag (AI disclosure required at upload)
AI_SOURCES = {SOURCE_AI_GOOGLEFLOW}
# known valid source tags
KNOWN_SOURCES = {SOURCE_ORIGINAL, SOURCE_AI_GOOGLEFLOW, SOURCE_DOWNLOAD}

# asset kinds
KIND_VIDEO = "video"
KIND_IMAGE = "image"
KIND_VECTOR = "vector"
KINDS = {KIND_VIDEO, KIND_IMAGE, KIND_VECTOR}

REGISTRY_NAME = "registry.json"


class GuardrailError(Exception):
    """Raised when an asset violates the IP-source policy."""


@dataclass
class Asset:
    file: str                       # path relative to batch dir (or absolute)
    kind: str                       # video | image | vector
    source: str                     # original | ai_googleflow | download
    is_ai: bool = False             # AI-generated (disclosure required)
    sketch: str | None = None       # originating sketch/style, if any
    seed: int | None = None
    width: int | None = None
    height: int | None = None
    aspect: str | None = None
    tags: list[str] = field(default_factory=list)
    added_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    def __post_init__(self):
        if self.kind not in KINDS:
            raise GuardrailError(f"unknown kind {self.kind!r} (allowed: {sorted(KINDS)})")
        if not self.source or self.source not in KNOWN_SOURCES:
            raise GuardrailError(
                f"asset {self.file!r} has missing/unknown source {self.source!r}; "
                f"must be one of {sorted(KNOWN_SOURCES)}"
            )
        # AI sources always carry the disclosure flag
        if self.source in AI_SOURCES:
            self.is_ai = True

    @property
    def sellable(self) -> bool:
        return self.source in SELLABLE_SOURCES


def assert_sellable(asset: Asset) -> None:
    """Hard block: refuse any asset that is not legal to sell on Adobe Stock."""
    if asset.source == SOURCE_DOWNLOAD:
        raise GuardrailError(
            f"REFUSED {asset.file!r}: source=download (Pexels/Pixabay/internet) is "
            f"NOT your IP and cannot be uploaded to Adobe Stock. Reselling others' "
            f"work = copyright infringement + contributor ban."
        )
    if not asset.sellable:
        raise GuardrailError(
            f"REFUSED {asset.file!r}: source={asset.source!r} is not sellable "
            f"(allowed: {sorted(SELLABLE_SOURCES)})."
        )


# --- registry persistence ----------------------------------------------------

class Registry:
    """Load/save the per-batch asset manifest (registry.json)."""

    def __init__(self, path: Path, assets: list[Asset] | None = None):
        self.path = path
        self.assets: list[Asset] = assets or []

    @classmethod
    def load(cls, batch_dir: Path) -> "Registry":
        path = batch_dir / REGISTRY_NAME
        assets: list[Asset] = []
        if path.exists():
            for raw in json.loads(path.read_text()):
                assets.append(Asset(**raw))
        return cls(path, assets)

    def save(self) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps([asdict(a) for a in self.assets], indent=2))
        return self.path

    def add(self, asset: Asset, *, enforce: bool = True) -> Asset:
        """Add an asset. With enforce=True (default) a non-sellable source raises."""
        if enforce:
            assert_sellable(asset)
        self.assets.append(asset)
        return asset

    def of_kind(self, kind: str) -> list[Asset]:
        return [a for a in self.assets if a.kind == kind]

    def sellable(self) -> list[Asset]:
        return [a for a in self.assets if a.sellable]

    def blocked(self) -> list[Asset]:
        return [a for a in self.assets if not a.sellable]

    def validate(self) -> list[str]:
        """Return a list of guardrail violation messages (empty = all clear)."""
        errs: list[str] = []
        for a in self.assets:
            try:
                assert_sellable(a)
            except GuardrailError as e:
                errs.append(str(e))
        return errs
