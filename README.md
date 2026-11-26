# Dashboard Piutang — PLN UP3 Makassar Selatan

Web-based dashboard yang mengacu pada referensi Looker Studio (**Niaga dan Pelayanan Pelanggan — CASH IN & KINERJA**) dan terhubung langsung ke database Google Sheets **`SALDO TUNGGAKAN AMS`**, lengkap dengan tombol eksekusi berurutan untuk 2 script Python (`uat.py` → `update_saldo_db.py`) dengan live log terminal (SSE).

## Fitur Utama

1. **Tab `CASH IN` (sesuai Looker Studio):**
   - **KPI Scorecards & Gauge:** Saldo Saat Ini (`Rp PTL`), Total Pelanggan, dan Gauge Target (`0` – `600 jt`).
   - **SALDO UNIT:** Pivot table per UNIT (`32111`–`32161` + `UP3`) × Lembar (`1`, `2`, `3`, `UP3`) dengan highlight hijau untuk sel nol (`-`) dan klik baris untuk filter cepat.
   - **SALDO PER KOGOL:** Ringkasan pelanggan & Rp PTL per Kogol.
   - **Filter Interaktif & LIST DATA DETIL PELANGGAN:** Filter Saldo (`>=`, `>`, `=`, `<=`, `<`), ULP, RBM, Lembar, KOGOL, Segmen Tarif, Tarif, Daya, pencarian cepat, sorting kolom, pagination, dan **Export CSV**.
   - **Analisis Harian (`SALDOHARIAN`):** `GRAFIK PENURUNAN PIUTANG` (Bulan Lalu vs Bulan Ini), `TABEL PERBANDINGAN TANGGAL`, dan `TABEL PERBANDINGAN ULP`.
   - **Komposisi & Master Join:** `KOMPOSISI TUNGGAKAN PER TARIF`, `SALDO KOGOL 3 PER PEMDA` (`MASTER_PEMDA`), `KOMPOSISI TUNGGAKAN PER UNIT`, dan `SALDO PER BILLER` (`MASTER_BILLER`).
2. **Tab `KINERJA`:**
   - Target vs Realisasi Saldo Piutang, Pencapaian PRR (`1. PRR`, `2. Ex-PRR`, `3. Prabayar`), grafik perbandingan per ULP, tren bulanan, dan tabel detail `KINERJA`.
3. **Tombol Eksekusi Berurutan (`▶ Eksekusi UAT → Update Saldo DB`):**
   - **Step 1 (`scripts/uat.py`):** Login SSO New AP2T, ambil `user_token` & `cookie`, simpan ke `scripts/user_token.json` (dan otomatis sinkron ke `D:\BOT\user_token.json` jika dijalankan di Windows).
   - **Step 2 (`scripts/update_saldo_db.py`):** Berjalan otomatis setelah Step 1 sukses — membaca `user_token.json`, menarik detail tunggakan 6 UNITUP secara paralel, menyimpan Excel lokal, dan push ke Google Sheets (`DETILTUNGGAKAN`).
   - **Step 3 (Auto-Refresh):** Menyegarkan cache dashboard secara otomatis.
   - Dilengkapi **Live Terminal Log (SSE)**, pilihan menjalankan masing-masing script secara terpisah, input periode `THBL`, dan tombol **Stop**.

## Struktur Direktori

```
dashboard-piutang-ams/
├── server.py                  # HTTP Server + REST API + SSE Log Stream
├── data_service.py            # Loader Google Sheets CSV + Cache + Agregasi
├── pipeline_runner.py         # Runner berurutan uat.py -> update_saldo_db.py
├── scripts/
│   ├── uat.py                 # Script ambil User Token Bearer New AP2T
│   └── update_saldo_db.py     # Script scrape 6 UNITUP & push Google Sheets
├── static/
│   ├── index.html
│   ├── styles.css
│   └── app.js
├── requirements.txt
├── start.sh                   # Launcher macOS / Linux
└── start.bat                  # Launcher Windows
```

## Cara Menjalankan

```bash
# 1. Install dependensi (pandas, requests, openpyxl sudah cukup untuk dashboard)
pip install -r requirements.txt

# 2. Jalankan server
python3 server.py --port 8080
# atau di Windows: double-click start.bat
```

Buka browser ke: **http://localhost:8080**

## Konfigurasi Opsional (Environment Variables)

- `PORT` — Port server (default `8080`)
- `GSHEETS_ID` — ID Google Spreadsheet (default `1Y23fh3aMdQNHGyqZncsAdDpsMT15K6Z0niCbfuUJnH0`)
- `THBL` — Periode tarik data default (format `YYYYMM`)
- `ENKRIPSI_EXE_PATH` — Path `Enkripsi_AP2T.exe` di Windows (default `D:\BOT\Enkripsi_AP2T.exe`)
- `IAM_USERNAME`, `IAM_PASSWORD`, `WEBMAIL_PASSWORD` — Kredensial untuk `scripts/uat.py`
