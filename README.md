# stock-visual-gen (stockgen)

Generate **100% original** motion-graphics clips (yours to sell) + Adobe Stock CSV metadata.
Upload freely — every asset is your own IP, not a resell.

## 4 Key Features

| Feature | Description |
|---|---|
| Smart AI Vision Recognition | AI reads vector/video/image visual concepts in depth — color, mood, style, composition — to auto-generate relevant titles & keywords |
| Batch Processing | Process dozens of assets at once in a single click (multi-file drag & drop or `stockgen import ./folder`) |
| High-Ranking SEO Keywords | 30–50 relevant, high-search-volume keywords per asset, optimized per kind (video/image/vector) to help reach microstock front pages |
| Export CSV Ready | Metadata is not embedded in files — originals stay untouched and safe, ready to export as CSV for bulk Adobe Stock upload |

## Pipeline

```
                    ┌─ Smart AI Vision (moondream) ─ reads visual concepts
                    │         ↓
  assets (image/video/vector) ──→ Batch Processing (dozens at once)
                    │         ↓
                    │   SEO Keywords 30-50 (per-kind trending terms)
                    │         ↓
                    └─ Export CSV (separate metadata, originals safe) ──→ Adobe Stock
```

Asset sources:
- `ytgen` (Pexels/Pixabay) = **must NOT** be resold — that is someone else's work
- `stockgen` (p5.js render / SVG generator / original import) = **100% your IP** — legal to sell

## Sketch Gallery (original, seed-reproducible)

| Sketch | Style |
|---|---|
| `particles` | Flow-field particle systems (abstract motion) |
| `gradient` | Flowing gradient / plasma fields |
| `waves` | Layered sine-wave landscapes |
| `nebula` | Cinematic bokeh / light / smoke loops |
| `data` | Animated abstract data-viz shapes |
| `globe` | Globe / sphere abstract |

Vector styles (flat, scalable): `icons`, `burst`, `waves`, `mosaic`, `orbit`

## Setup

```bash
cd /Users/mac/Code/stock-visual-gen
uv venv --python 3.11 && uv pip install -e .
npm install                          # puppeteer for headless rendering
brew services start ollama
ollama pull llama3.2:3b               # text LLM for titles/keywords
ollama pull moondream                 # vision model for Smart AI Vision

stockgen doctor                       # check all components
```

## Quick Start

### Batch Processing — dozens of assets in one click

```bash
# From a folder (CLI) — auto-detects kind per file
stockgen import ./my_assets --source original              # mixed image+video
stockgen import ./my_assets --source original --kind vector  # all as vector

# From the Web UI — multi-file drag & drop
stockgen ui                                           # opens http://127.0.0.1:8765
# -> "Batch" tab -> drop dozens of files at once -> click "Process batch"
```

### Generate from sketches

```bash
stockgen vector --style all --count 3                 # original flat vectors
stockgen image --sketch all --count 3 --format jpg    # high-res raster >=4MP
stockgen render --sketch particles --count 5          # 4K loop video
stockgen ingest ./ai_videos --source ai_googleflow    # AI video (paid plan only)
```

### Smart AI Vision (automatic)

No need to type a description — leave it empty and AI will look at the asset:

- **Video**: extracts a representative frame (35% duration) → moondream deep reading
- **Image**: reads directly → style, color, mood, composition
- **Vector**: rasterizes SVG → preview JPG → vision

Description priority: manual input > AI Vision > filename

```bash
stockgen metadata --batch batch_20260911_212257        # triggers vision + CSV
```

### Export CSV (metadata not embedded)

Original files are **never modified**. Metadata lives only in separate CSVs:

```
output/batch_20260911_212257/
  image/img_001.jpg              # original safe (md5 unchanged)
  video/vid_001_native.mp4       # original safe
  vector/vec_001.eps             # + vec_001.svg (master) + _preview.jpg
  metadata_image.csv             # 30-50 keywords per image
  metadata_video.csv             # 30-50 keywords per video
  metadata_vector.csv            # 30-50 keywords per vector
  metadata.csv                   # combined (all kinds, single upload)
  registry.json                  # manifest + source + is_ai + desc
  upload_checklist.txt           # reminder: tick AI, check releases
```

Upload to Adobe Stock: drag asset files + the matching CSV to the contributor portal.

### Web UI

```bash
stockgen ui                                              # new batch
stockgen ui --batch batch_20260911_212257                # resume existing batch
stockgen ui --port 8765 --no-browser                     # custom port
```

Tabs: **Batch** (dozens of assets) | **Upscale → 4K** | **Raster → SVG** | **Video** | **Metadata / Export**

### All Commands

```bash
stockgen doctor                    # check: ffmpeg, node, puppeteer, cairosvg, ollama, vision, seo, csv
stockgen ui                        # web UI drag & drop
stockgen menu                      # interactive terminal menu
stockgen import ./folder           # batch import folder (NEW)
stockgen image --count 5           # generate images
stockgen vector --count 5          # generate vectors
stockgen render --count 5          # render videos
stockgen ingest ./videos --source ai_googleflow
stockgen upscale <file> --source original --to 4k
stockgen vectorize <raster> --source original --engine vtracer
stockgen metadata --batch <name> --kind all|image|video|vector
stockgen assets --batch <name>     # list + validate registry
```

## Configuration (config.yaml)

```yaml
metadata:
  provider: ollama              # ollama | groq | rule
  ollama_model: llama3.2:3b     # text LLM
  vision_model: moondream       # Smart AI Vision
  auto_describe: true           # auto vision when desc is empty
  keywords_count: 42            # 30-50 (clamped to 49 = Adobe max)
  seo_boost: true               # trending terms per kind
  default_category: 8           # Adobe category ID
```

## SEO Keywords — How It Works

Every asset gets 30–50 keywords (verified `30 <= n <= 50`):

1. Content words from Smart AI Vision (most relevant, placed first)
2. Per-kind vocab (video: 4k/loop/motion, vector: eps/svg/flat, etc.)
3. SEO_BOOST trending terms per kind (business, corporate, template, social media, ...)
4. Forbidden words stripped for AI content (veo, midjourney, etc.)

Order = relevance. Adobe Stock reads keywords left to right.

## Output per Batch

```
output/batch_<timestamp>/
  _src/                          # original upload backup
  _vision/                       # frames extracted for vision
  image/img_001.jpg              # >=4MP, sRGB, JPEG quality 92
  video/vid_001_native.mp4       # native res, H.264 CRF14 (Adobe-compliant)
  vector/vec_001.eps             # EPSF-3.0 + .svg + _preview.jpg
  metadata_image.csv             # Adobe Stock format: Filename,Title,Keywords,Category,Releases
  metadata_video.csv
  metadata_vector.csv
  metadata.csv                   # combined (all kinds)
  registry.json                  # source, is_ai, desc, seed, aspect
  upload_checklist.txt
```

**Do not rename files inside a batch** — the registry relies on paths. Use `--batch` to resume a batch.

## Legal & Guardrails

- Only `source=original` (made by stockgen) and `source=ai_googleflow` (paid plan) are sellable
- `source=download` (Pexels/Pixabay/internet) = **hard-blocked** in every pipeline (upscale, vectorize, batch, metadata)
- AI content from Google Flow/Veo: ensure a paid plan (commercial rights), metadata auto-strips generator names, tick "Created using generative AI tools" on upload
- Adobe Stock **forbids up-res** HD→4K — submit at native resolution (use `Prepare native for Adobe`, not Upscale→4K for upload)

## Latest Verification

```
batch_20260911_212257: 7 assets (4 image + 1 video + 2 vector)
  image: 38-40 keywords ✓ | video: 42 keywords ✓ | vector: 42 keywords ✓
  vision: moondream deep reading ✓ | batch: 1-click 6 files ✓ | CSV non-embedded ✓
  doctor: 10/10 checks passed
```
