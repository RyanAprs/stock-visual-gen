# stock-visual-gen (stockgen)

Generate **100% original** motion-graphics clips (yours to sell) + Adobe Stock CSV metadata.
Upload silakan — semua aset adalah IP kamu sendiri, bukan resell.

## 4 Fitur Utama

| Fitur | Deskripsi |
|---|---|
| Smart AI Vision Recognition | AI membaca konsep visual (vektor/video/image) secara mendalam — warna, mood, style, komposisi — untuk judul & keyword yang relevan otomatis |
| Batch Processing | Proses puluhan aset sekaligus dalam satu klik (drag & drop multi-file atau `stockgen import ./folder`) |
| High-Ranking SEO Keywords | 30–50 kata kunci relevan berpencarian tinggi per aset, teroptimasi per kind (video/image/vector) agar mudah tembus halaman utama microstock |
| Export CSV Ready | Metadata tidak tertanam pada file — file asli tetap aman tanpa modifikasi, siap export ke CSV untuk upload massal Adobe Stock |

## Pipeline

```
                    ┌─ Smart AI Vision (moondream) ─ membaca konsep visual
                    │         ↓
  aset (image/video/vector) ──→ Batch Processing (puluhan sekaligus)
                    │         ↓
                    │   SEO Keywords 30-50 (per-kind trending terms)
                    │         ↓
                    └─ Export CSV (metadata terpisah, file asli aman) ──→ Adobe Stock
```

Sumber aset:
- `ytgen` (Pexels/Pixabay) = **TIDAK boleh** dijual kembali — itu karya orang lain
- `stockgen` (p5.js render / SVG generator / import original) = **100% IP kamu** — legal untuk dijual

## Galeri Sketch (original, seed-reproducible)

| Sketch | Gaya |
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
npm install                          # puppeteer untuk headless render
brew services start ollama
ollama pull llama3.2:3b               # text LLM untuk judul/keyword
ollama pull moondream                 # vision model untuk Smart AI Vision

stockgen doctor                       # cek semua komponen
```

## Penggunaan Cepat

### Batch Processing — puluhan aset sekaligus (1 klik)

```bash
# Dari folder (CLI) — auto-detect kind per file
stockgen import ./asetku --source original              # image+video campur
stockgen import ./asetku --source original --kind vector  # semua jadi vector

# Dari Web UI — drag & drop multi-file
stockgen ui                                           # buka http://127.0.0.1:8765
# -> Tab "Batch" -> drop puluhan file sekaligus -> klik "Proses batch"
```

### Generate dari sketch

```bash
stockgen vector --style all --count 3                 # vector flat original
stockgen image --sketch all --count 3 --format jpg    # raster high-res >=4MP
stockgen render --sketch particles --count 5          # video 4K loop
stockgen ingest ./video_ai --source ai_googleflow     # video AI (paid plan only)
```

### Smart AI Vision (otomatis)

Tidak perlu ketik deskripsi — kosongkan saja, AI akan melihat aset:

- **Video**: ekstrak frame representatif (35% durasi) → moondream deep reading
- **Image**: baca langsung → style, warna, mood, komposisi
- **Vector**: rasterize SVG → preview JPG → vision

Prioritas deskripsi: input manual > AI Vision > nama file

```bash
stockgen metadata --batch batch_20260911_212257        # trigger vision + CSV
```

### Export CSV (metadata tidak tertanam)

File asli **tidak pernah dimodifikasi**. Metadata hanya di CSV terpisah:

```
output/batch_20260911_212257/
  image/img_001.jpg              # file asli aman (md5 tidak berubah)
  video/vid_001_native.mp4       # file asli aman
  vector/vec_001.eps             # + vec_001.svg (master) + _preview.jpg
  metadata_image.csv             # 30-50 keywords per image
  metadata_video.csv             # 30-50 keywords per video
  metadata_vector.csv            # 30-50 keywords per vector
  metadata.csv                   # combined (semua kind, single upload)
  registry.json                  # manifest + source + is_ai + desc
  upload_checklist.txt           # reminder: centang AI, cek release
```

Upload ke Adobe Stock: drag file aset + CSV yang sesuai ke contributor portal.

### Web UI

```bash
stockgen ui                                              # batch baru
stockgen ui --batch batch_20260911_212257                # lanjutkan batch
stockgen ui --port 8765 --no-browser                     # custom port
```

Tabs: **Batch** (puluhan aset) | **Upscale → 4K** | **Raster → SVG** | **Video** | **Metadata / Export**

### Command Lengkap

```bash
stockgen doctor                    # cek: ffmpeg, node, puppeteer, cairosvg, ollama, vision, seo, csv
stockgen ui                        # web UI drag & drop
stockgen menu                      # menu interaktif terminal
stockgen import ./folder           # batch import folder (NEW)
stockgen image --count 5           # generate image
stockgen vector --count 5          # generate vector
stockgen render --count 5          # render video
stockgen ingest ./video --source ai_googleflow
stockgen upscale <file> --source original --to 4k
stockgen vectorize <raster> --source original --engine vtracer
stockgen metadata --batch <name> --kind all|image|video|vector
stockgen assets --batch <name>     # list + validate registry
```

## Konfigurasi (config.yaml)

```yaml
metadata:
  provider: ollama              # ollama | groq | rule
  ollama_model: llama3.2:3b     # text LLM
  vision_model: moondream       # Smart AI Vision
  auto_describe: true           # vision otomatis jika desc kosong
  keywords_count: 42            # 30-50 (clamp ke 49 = max Adobe)
  seo_boost: true               # trending terms per kind
  default_category: 8           # Adobe category ID
```

## SEO Keywords — Cara Kerja

Setiap aset dapat 30–50 keywords (verified `30 <= n <= 50`):

1. Content words dari Smart AI Vision (paling relevan, di depan)
2. Per-kind vocab (video: 4k/loop/motion, vector: eps/svg/flat, dll)
3. SEO_BOOST trending terms per kind (business, corporate, template, social media, ...)
4. Strip kata terlarang untuk AI content (veo, midjourney, dll)

Urutan = relevansi. Adobe Stock membaca keywords dari kiri ke kanan.

## Output per Batch

```
output/batch_<timestamp>/
  _src/                          # file upload asli (backup)
  _vision/                       # frame ekstrak untuk vision
  image/img_001.jpg              # >=4MP, sRGB, JPEG quality 92
  video/vid_001_native.mp4       # native res, H.264 CRF14 (Adobe-compliant)
  vector/vec_001.eps             # EPSF-3.0 + .svg + _preview.jpg
  metadata_image.csv             # Adobe Stock format: Filename,Title,Keywords,Category,Releases
  metadata_video.csv
  metadata_vector.csv
  metadata.csv                   # combined (semua kind)
  registry.json                  # source, is_ai, desc, seed, aspect
  upload_checklist.txt
```

**Jangan rename file di dalam batch** — registry mengandalkan path. Gunakan `--batch` untuk melanjutkan batch.

## Legal & Guardrail

- Hanya `source=original` (buatan stockgen) dan `source=ai_googleflow` (paid plan) yang sellable
- `source=download` (Pexels/Pixabay/internet) = **hard-blocked** di semua pipeline (upscale, vectorize, batch, metadata)
- AI content dari Google Flow/Veo: pastikan plan berbayar (hak komersial), metadata otomatis strip nama generator, centang "Created using generative AI tools" saat upload
- Adobe Stock **melarang up-res** HD→4K — submit native resolution (gunakan `Prepare native for Adobe`, bukan Upscale→4K untuk upload)

## Verifikasi Terbaru

```
batch_20260911_212257: 7 aset (4 image + 1 video + 2 vector)
  image: 38-40 keywords ✓ | video: 42 keywords ✓ | vector: 42 keywords ✓
  vision: moondream deep reading ✓ | batch: 1 klik 6 file ✓ | CSV non-embedded ✓
  doctor: 10/10 checks passed
```
