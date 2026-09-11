#!/bin/bash
# SKPI Prestasi Akademik — update via prestasi_akd_Prodi/edit_save
# Controller: prestasi_akd_Prodi (endpoint prodi)

COOKIES='_ga=GA1.1.887546975.1787797973; _ga_87JFRNKQWM=GS2.1.s1787883138$o3$g0$t1787883138$j60$l0$h0; _ga_4CTSDV02H2=GS2.1.s1788406579$o1$g0$t1788406581$j58$l0$h0; role=admin; _clck=mo1a19%5E2%5Eg9b%5E0%5E2443; _ga_0F1NKMSQDL=GS2.1.s1788949059$o2$g0$t1788949059$j60$l0$h0; _ga_9GSZKDCXHL=GS2.1.s1788949059$o2$g0$t1788949059$j60$l0$h0; __okwg08040wo04wkcc0cok0o0w8cwkog4gsgog40w=46f06e28693af8d78d2326595a60bc2e00ea870a; cf_clearance=HYitgyEXOkykS6OwZLkhWIYg4xTYBArwlNlsJr8JlYk-1789110793-1.2.1.1-_KC7K3FW6Gf9BLma6V2HOCcLbKOYJ5pGegDiAxy.lPaeryfSDfysO2xjXL8fq1LXX0tpZn0yjg.8eg822UkDnpcaDRNTB_KgRxCqOgjRR8jvGCzXNMQDBR6qEU.fw3GTbcsAkTThLcfUC.LmMaYeYQkCKMSWOs_BRMaWH1pV.LkymKmM7kHCpP8ApBU7dWWKTLOw0ugrZSXwzS2KUQXUk8ATogrr3qzr2HTqsLTeJnST4jAc94WhKGNLdJU8YdkJnNIwT6R9rgfpQmi0_e0XgHCZaI.nCQCudDbt4SfLiK8.ORsm9IQbh8IhW5yOOk03ypBdbQwr28GgDVQ15O5gjsfq4ylb62SkPQnbR9t.n5aUBsjVm2ASJ0Zm5Ey8ZQzsIgA5gxqvIdygiHID6iXYGNLnXHDhAy._.KaeTLlw3Cxc0ED8nBVYMEGZ.xmwHQzeuc.nGQ.5NPrWHEYEXeAsLarHi4s0CAJt7x.WWnHhVXkebiKm4NVw.AEJ07QVx7i3B6MbzQEOFI62fHUGqYRRKw'

BASE="https://skpi.unimma.ac.id/administrator/prestasi_akd_Prodi/edit_save"

do_update() {
  local id="$1"
  local prestasi_indo="$2"
  local prestasi_english="$3"
  local lembaga="$4"
  local file_name="$5"
  local tgl_upload="$6"
  local kategori="$7"

  echo ""
  echo "=== Updating ID $id: $prestasi_indo ==="
  echo "    Kategori: $kategori | English: $prestasi_english"

  curl -sS -X POST "${BASE}/${id}" \
    -H 'Accept: application/json, text/javascript, */*; q=0.01' \
    -H 'Content-Type: application/x-www-form-urlencoded; charset=UTF-8' \
    -H 'X-Requested-With: XMLHttpRequest' \
    -H "Cookie: ${COOKIES}" \
    -H 'User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36' \
    -H 'Referer: https://skpi.unimma.ac.id/administrator/prestasi_akd_Mhs' \
    --data-urlencode "prestasi_indo=${prestasi_indo}" \
    --data-urlencode "prestasi_non_indo=${prestasi_indo}" \
    --data-urlencode "prestasi_english=${prestasi_english}" \
    --data-urlencode "prestasi_non_english=${prestasi_english}" \
    --data-urlencode "lembaga=${lembaga}" \
    --data-urlencode "prestasi_akd_file_uuid=" \
    --data-urlencode "prestasi_non_akd_file_uuid=" \
    --data-urlencode "prestasi_akd_file_name=${file_name}" \
    --data-urlencode "prestasi_non_akd_file_name=${file_name}" \
    --data-urlencode "save_type=back" \
    --data-urlencode "tgl_upload=${tgl_upload}" \
    --data-urlencode "status=2" \
    --data-urlencode "kategori=${kategori}" \
    --data-urlencode "Kategori=${kategori}" \
    --data-urlencode "id_kategori=${kategori}" \
    --data-urlencode "kategori_id=${kategori}"

  echo ""
  echo "--- Response above ---"
  sleep 1
}

# 1. Lomba Web Design Festival SI 2025 (ID 119148) — Kategori 4 (Penghargaan)
do_update 119148 \
  "Lomba Web Design Festival Sistem Informasi 2025" \
  "Web Design Competition - Information Systems Festival (2025)" \
  "Institut Pendidikan Indonesia Garut" \
  "20260908112313-2026-09-08prestasi_akd111927.jpg" \
  "2026-09-08" \
  "4"

# 2. Studi Independen Bersertifikat Angkatan 7 (ID 119130) — Kategori 2 (Kompetensi)
do_update 119130 \
  "Studi Independen Bersertifikat Angkatan 7" \
  "Certified Independent Study Batch 7 (2024)" \
  "PT Hacktivate Teknologi Indonesia" \
  "20260908111601-2026-09-08prestasi_akd111532.jpg" \
  "2026-09-08" \
  "2"

# 3. KKN (ID 119113) — Kategori 1 (Aktif Kegiatan)
do_update 119113 \
  "Kuliah Kerja Nyata (KKN)" \
  "Community Service (2025)" \
  "LP3M_UMM" \
  "20260908110848-2026-09-08prestasi_akd110837.jpg" \
  "2026-09-08" \
  "1"

# 4. Ujian Al-Qur'an dan Ibadah (ID 119104) — Kategori 2 (Kompetensi)
do_update 119104 \
  "Ujian Al-Qur'an dan Ibadah" \
  "Test of Al Qur'an and Worshiping Practice (2025)" \
  "LP2SI_UMM" \
  "20260908110357-2026-09-08prestasi_akd110352.jpeg" \
  "2026-09-08" \
  "2"

# 5. General English Course (ID 119101) — Kategori 3 (Pelatihan)
do_update 119101 \
  "General English Course" \
  "General English Course (2023)" \
  "Pusat Bahasa _UMM" \
  "20260908110314-2026-09-08prestasi_akd110236.jpeg" \
  "2026-09-08" \
  "3"

# 6. Pelatihan Dasar Ketrampilan Komputer (ID 119097) — Kategori 3 (Pelatihan)
do_update 119097 \
  "Pelatihan Dasar Ketrampilan Komputer" \
  "Basic Computer Skills Training (2023)" \
  "PUSKOM _UMM" \
  "20260908110150-2026-09-08prestasi_akd110112.jpeg" \
  "2026-09-08" \
  "3"

echo ""
echo "=================================================="
echo "SEMUA 6 DATA PRESTASI AKADEMIK SELESAI DIPROSES"
echo "=================================================="
