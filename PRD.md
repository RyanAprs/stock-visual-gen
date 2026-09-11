# PRD — stockgen v2: Full Adobe Stock Contributor Automation

Status: DRAFT for review
Owner: user
Repo: /Users/mac/Code/stock-visual-gen (extend existing stockgen)
Last updated: 2026-09-11

---

## 1. Tujuan

Perluas `stockgen` dari "render motion-graphics + CSV" jadi pipeline OTOMASI PENUH
untuk contributor Adobe Stock: sekali generate → banyak asset (vector/image/video)
siap upload + metadata CSV batch yang bikin stock cepat laku.

Tiga jalur output:
1. VIDEO 4K  — .mp4, >=8MP (3840x2160), seamless loop.
2. IMAGE     — .jpg/.png/.webp high-res, siap jual.
3. VECTOR    — .svg + .eps (Adobe Stock butuh EPS untuk vektor).

Semua dengan metadata AI (Title + 49 keyword + Category) di satu CSV per batch.

---

## 2. Guardrail IP (WAJIB — desain inti, bukan opsional)

Adobe Stock contributor HARUS pemilik/pencipta tiap asset. Ini menentukan sumber
yang boleh masuk pipeline. Tiap asset WAJIB punya field `source`:

| source           | Sellable? | Syarat                                                        |
|------------------|-----------|---------------------------------------------------------------|
| `original`       | YA        | Dibuat stockgen (p5.js render / SVG generator) = IP user.     |
| `ai_googleflow`  | YA*       | Google Flow/Veo dari PLAN BERBAYAR (hak komersial). *lihat 2a |
| `download`       | TIDAK     | Pexels/Pixabay/internet → DITOLAK pipeline. Hard block.       |

Tool WAJIB menolak (exit error) asset ber-source `download` atau tak bertanda,
sebelum masuk tahap metadata/export. Ini mencegah ban akun.

### 2a. Aturan konten AI (Google Flow / Veo)
- Hanya dari plan berbayar (Google AI Pro/Ultra) yang memberi hak komersial.
- Metadata WAJIB set flag `is_ai_generated = true` → nanti dicentang saat upload.
- Title/Keywords DILARANG menyebut nama generator ("veo", "google flow", dll)
  → tool auto-strip kata terlarang dari metadata.
- Hindari wajah realistis, logo/merek, karakter berhak cipta, landmark bermerek.
- Konten aman: abstrak, objek, alam, tekstur, motion background.

---

## 3. Arsitektur (extend, bukan rewrite)

Reuse yang ada:
- `config.py`, `render.py` (p5.js→ffmpeg 4K), `metadata.py` (LLM/rule CSV),
  `music.py`, `assemble.py`, `checks.py`, CLI di `main.py`.

Modul BARU di `src/stockgen/`:
```
assets.py      # asset registry: satu manifest gabungan (video+image+vector),
               # tiap item {file, kind, source, is_ai, sketch/tags, ...}.
image.py       # generate/proses raster: PNG/JPG/WEBP high-res dari sketch p5.js
               # (mode still-frame), + upscale.
vector.py      # generate ikon/ilustrasi flat original → SVG, lalu SVG→EPS.
upscale.py     # upscale video HD→4K & image, HANYA untuk asset original/ai.
ingest.py      # intake asset AI Google Flow: tandai source=ai_googleflow,
               # validasi resolusi, salin ke batch, catat ke registry.
export.py      # susun CSV multi-kind (kolom Adobe Stock benar per tipe).
```

CLI baru (subcommand di `main.py`):
```
stockgen image   --sketch all --count N --format webp   # raster original
stockgen vector  --style icons --count N                # SVG+EPS original
stockgen upscale  <path> --to 4k                        # original/ai only
stockgen ingest   <dir> --source ai_googleflow          # intake video AI
stockgen metadata --batch <name> --kind all             # CSV semua tipe
stockgen generate                                       # interaktif, all-in-one
```

---

## 4. Detail per jalur

### 4.1 VIDEO 4K
- Original: sudah jalan (render.py, libx264 crf18, yuv420p, 3840x2160).
- AI Google Flow: `ingest` — validasi >=4MP & durasi, salin, source=ai_googleflow,
  is_ai=true. TOLAK jika resolusi < floor Adobe Stock.
- Upscale HD→4K (real-ESRGAN video / ffmpeg lanczos sebagai fallback gratis)
  hanya untuk asset original/ai.

### 4.2 IMAGE (raster jual)
- Sumber: still-frame dari sketch p5.js (render 1 frame, seed beda = varian).
- Output format: jpg (default Adobe), + opsi png/webp. Min 4MP; target
  4000px sisi panjang. sRGB, tanpa alpha untuk jpg.
- Metadata image CSV: Filename, Title, Keywords, Category, Releases.

### 4.3 VECTOR (SVG + EPS)
- Fokus: ikon/ilustrasi FLAT original (jawaban user) — bersih, cocok vektor.
- Dua sumber:
  a. Generator SVG programatik (bentuk/pola/ikon parametrik dari seed) = original.
  b. Raster→vector: HANYA untuk raster original stockgen (bukan gambar download).
     Engine: `vtracer` (gratis, rust, flat art bagus) atau `potrace` (mono).
- SVG→EPS: `inkscape --export-type=eps` (gratis) atau `cairosvg`→pdf→eps chain.
- Adobe Stock vektor: upload EPS (v8/10) + JPEG preview; SVG disimpan sebagai master.

---

## 5. Metadata & CSV (perluas metadata.py)

- Tambah kosakata untuk `image` & `vector` (bukan cuma sketch video).
- Title/keyword per-kind: vektor pakai "vector, icon, flat, illustration, eps";
  image pakai "photo/graphic, background, high resolution".
- Flag AI: kolom internal `is_ai` → dipakai untuk reminder centang saat upload
  (Adobe CSV standar tak punya kolom AI; wajib dicentang manual di web/portal).
- Auto-strip kata generator terlarang dari Title/Keywords.
- Satu CSV per batch, atau per-kind (`metadata_video.csv`, `_image.csv`, `_vector.csv`)
  karena Category & konteks beda per tipe.
- Provider tetap: ollama (llama3.2:3b) | groq | rule (fallback deterministik).

---

## 6. Output layout (per project, konsisten dgn aturan existing)

```
output/batch_<ts>/
  video/   clip_NNN.mp4
  image/   img_NNN.jpg|png|webp
  vector/  vec_NNN.svg  vec_NNN.eps  vec_NNN_preview.jpg
  registry.json          # semua asset + source + is_ai + status
  metadata_video.csv
  metadata_image.csv
  metadata_vector.csv
  upload_checklist.txt    # reminder: centang AI, cek release, dll
```
Deliverable tetap di folder per-batch, JANGAN di top-level (aturan user).

---

## 7. Milestones (incremental, verify tiap tahap live)

- M1  Registry + guardrail source (`assets.py`, hard-block `download`). VERIFY: reject test.
- M2  Metadata multi-kind + CSV per-kind (prioritas #1 user). VERIFY: CSV valid Adobe.
- M3  Vector original: SVG generator + SVG→EPS (`vector.py`). VERIFY: EPS buka di Illustrator/Inkscape.
- M4  Image raster: still-frame export jpg/png/webp (`image.py`). VERIFY: >=4MP, sRGB.
- M5  Ingest AI Google Flow (`ingest.py`) + flag is_ai + strip generator words. VERIFY: reject <4MP & free-plan warning.
- M6  Upscale HD→4K (`upscale.py`, original/ai only). VERIFY: 4K output valid.
- M7  Raster→vector (vtracer/potrace) untuk raster original saja. VERIFY: SVG bersih.
- M8  `generate` all-in-one interaktif + upload_checklist. VERIFY: satu run hasilkan multi-asset + CSV.

Prioritas urut sesuai user: METADATA/CSV dulu (M2), lalu vector (M3), lalu image/upscale.

---

## 8. Dependency (semua gratis)

- Ada: puppeteer, ffmpeg, p5.js, requests, pyyaml, ollama (opsional).
- Baru: `vtracer` atau `potrace` (raster→vector), `inkscape` (SVG→EPS) atau `cairosvg`,
  `Pillow` (image proc), `realesrgan-ncnn-vulkan`/`ffmpeg lanczos` (upscale gratis).
- Cek ketersediaan via `stockgen doctor` (extend checks.py).

---

## 9. Non-goals / batas tegas

- TIDAK memproses asset download (Pexels/Pixabay/internet) untuk dijual. Hard block.
- TIDAK vectorize foto realistis (hasil jelek) — fokus flat art.
- TIDAK auto-upload ke Adobe (user review manual dulu; sesuai preferensi).
- TIDAK menaruh deliverable di top-level output.

---

## 10. Risiko

- Free plan Google Flow mungkin TANPA hak komersial → wajib user pastikan plan berbayar.
  Tool cuma warning, tak bisa verifikasi plan.
- Adobe Stock reject rate tinggi untuk konten AI generik / duplikat → butuh variasi seed.
- Upscale gratis (ESRGAN/lanczos) kualitas < paid → set ekspektasi.
