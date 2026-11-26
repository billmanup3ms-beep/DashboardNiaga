import concurrent.futures
from datetime import datetime
import json as _json
import os
import sys
import time
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
import urllib3

# Ensure real-time stdout streaming when invoked from web dashboard
try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except Exception:
    pass

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
LOCK_FILE = os.path.join(SCRIPT_DIR, "update_saldo.lock")


def _load_dotenv():
    env_path = os.path.join(PROJECT_DIR, ".env")
    if not os.path.isfile(env_path):
        return
    with open(env_path, "r", encoding="utf-8") as ef:
        for line in ef:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


_load_dotenv()


def acquire_lock():
    pass


def release_lock():
    pass


# Nonaktifkan peringatan SSL certificate
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==============================================================================
# KONFIGURASI APLIKASI DAN GOOGLE SPREADSHEET
# ==============================================================================
COOKIE_STR = ""
TOKEN_BEARER = ""

TOKEN_CANDIDATES = [
    os.environ.get("USER_TOKEN_PATH", ""),
    os.path.join(SCRIPT_DIR, "user_token.json"),
    r"D:\BOT\user_token.json",
]

for _cand in TOKEN_CANDIDATES:
    if _cand and os.path.isfile(_cand):
        try:
            with open(_cand, "r", encoding="utf-8") as _tf:
                _tok_data = _json.load(_tf)
                _raw_token = _tok_data.get("user_token", "")
                if _raw_token and _raw_token != "INVALID":
                    TOKEN_BEARER = (
                        f"Bearer {_raw_token}"
                        if not _raw_token.startswith("Bearer ")
                        else _raw_token
                    )
                    COOKIE_STR = _tok_data.get("cookie", "")
                    print(f"[INFO] Menggunakan token dari: {_cand}")
                    break
        except Exception as _e:
            print(f"[WARNING] Gagal membaca {_cand}: {_e}")

if not TOKEN_BEARER:
    _env_tok = os.environ.get("TOKEN_BEARER", "")
    if _env_tok:
        TOKEN_BEARER = _env_tok if _env_tok.startswith("Bearer ") else f"Bearer {_env_tok}"
    else:
        print("[ERROR] user_token.json tidak ditemukan/tidak valid. Jalankan scripts/uat.py terlebih dahulu.")

WEB_APP_URL = os.environ.get(
    "GSHEETS_WEB_APP_URL",
    "",
)

WORKSHEET_NAME = "DETILTUNGGAKAN"
TARGET_ROW = 2  # Baris awal paste data (baris 1 untuk header)
THBL = os.environ.get("THBL", datetime.now().strftime("%Y%m"))

# Daftar UNITUP yang akan di-scrap
LIST_UNITUP = ["32111", "32121", "32131", "32141", "32151", "32161"]

# Jumlah thread worker untuk mendownload chunk secara paralel
MAX_CHUNK_WORKERS = 12

# Daftar kolom yang akan dihapus
COLS_TO_DROP = [
    "dayaFormatted",
    "lembarFormatted",
    "rpptlFormatted",
    "rpbpjuFormatted",
    "rpppnFormatted",
    "rpmatFormatted",
    "tagsusFormatted",
    "ujlFormatted",
    "bpFormatted",
    "rptrafoFormatted",
    "rpsewatrafoFormatted",
    "rpsewakapFormatted",
    "rptagFormatted",
    "rpbkFormatted",
]


def get_default_output_filename():
    if os.environ.get("OUTPUT_EXCEL_PATH"):
        return os.environ["OUTPUT_EXCEL_PATH"]
    if os.path.isdir(r"D:\BOT"):
        return r"D:\BOT\gabungan_detail_tunggakan.xlsx"
    data_dir = os.path.join(PROJECT_DIR, "data")
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, "gabungan_detail_tunggakan.xlsx")


def create_optimized_session(pool_size=20):
    """Membuat HTTP Session dengan connection pooling untuk performa tinggi."""
    session = requests.Session()
    session.trust_env = False

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Accept-Language": "id,en-US;q=0.9,en;q=0.8",
        "Authorization": TOKEN_BEARER.strip(),
        "Connection": "keep-alive",
        "Origin": "https://newap2t.pln.co.id",
        "Referer": "https://newap2t.pln.co.id/crm/ap2t",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML,"
            " like Gecko) Chrome/153.0.0.0 Safari/537.36"
        ),
        "Cookie": COOKIE_STR,
    }
    session.headers.update(headers)

    adapter = HTTPAdapter(pool_connections=pool_size, pool_maxsize=pool_size)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def drop_specified_columns(df, cols_to_drop):
    """Menghapus kolom-kolom yang ada pada daftar cols_to_drop."""
    existing_cols = [col for col in cols_to_drop if col in df.columns]
    if existing_cols:
        df = df.drop(columns=existing_cols)
        print(f"[INFO] Berhasil menghapus {len(existing_cols)} kolom kosong.")
    return df


def format_date_columns(df):
    """Mendeteksi dan mengubah kolom bertipe tanggal menjadi format string DD/MM/YYYY."""
    for col in df.columns:
        col_str = str(col).lower()
        if any(
            keyword in col_str
            for keyword in ["tgl", "date", "waktu", "created", "updated"]
        ):
            try:
                dt_series = pd.to_datetime(df[col], errors="coerce")
                if not dt_series.isna().all():
                    df[col] = dt_series.dt.strftime("%d/%m/%Y")
            except Exception:
                pass
    return df


def reorder_columns(df):
    """Memindahkan kolom 'UNITUP' ke posisi paling awal."""
    cols = list(df.columns)
    unitup_col = None

    for c in cols:
        if str(c).lower() == "unitup":
            unitup_col = c
            break

    if unitup_col:
        cols.remove(unitup_col)
        cols.insert(0, unitup_col)
        df = df[cols]

    return df


def sanitize_dataframe_for_json(df):
    """Mengubah DataFrame menjadi list 2D yang aman untuk JSON (bebas NaN/NaT/Null)."""
    clean_df = df.copy()
    clean_df = clean_df.astype(object).where(pd.notnull(clean_df), "")
    return clean_df.values.tolist()


def push_to_google_sheets(
    df,
    web_app_url,
    worksheet_name,
    start_target_row=2,
    chunk_size=3000,
    max_retries=10,
):
    """Mengirimkan seluruh isi dataframe ke Google Spreadsheet secara bertahap (batching)."""
    print("\n" + "=" * 70)
    print(f"[GOOGLE SHEETS] Mengirim data ke worksheet: {worksheet_name}")
    print(f"[GOOGLE SHEETS] Total data yang akan dikirim: {len(df)} baris")
    print(f"[GOOGLE SHEETS] Ukuran batch: {chunk_size} baris per request")
    print("=" * 70)

    # 1. Clear data lama di Google Sheets
    print(
        f"[GOOGLE SHEETS] Membersihkan baris lama mulai dari baris {start_target_row}..."
    )
    try:
        clear_payload = {
            "worksheet_name": worksheet_name,
            "action": "clear",
            "start_row": start_target_row,
        }
        clear_res = requests.post(web_app_url, json=clear_payload, timeout=900)
        if clear_res.status_code in [200, 302]:
            print("[GOOGLE SHEETS] Pembersihan data lama selesai.")
        else:
            print(
                "[WARNING GOOGLE SHEETS] Pembersihan data lama merespons status:"
                f" {clear_res.status_code}"
            )
    except Exception as e:
        print(f"[ERROR GOOGLE SHEETS] Perintah pembersihan gagal: {e}")

    # 2. Persiapkan data yang bersih
    data_list = sanitize_dataframe_for_json(df)
    total_rows = len(data_list)

    if total_rows == 0:
        print("[GOOGLE SHEETS] Data kosong. Tidak ada yang dikirim.")
        return

    current_target = start_target_row
    uploaded_count = 0

    # 3. Pengiriman per Batch
    for i in range(0, total_rows, chunk_size):
        chunk = data_list[i : i + chunk_size]
        payload = {
            "worksheet_name": worksheet_name,
            "target_row": current_target,
            "data": chunk,
        }

        batch_success = False

        for attempt in range(1, max_retries + 1):
            try:
                response = requests.post(web_app_url, json=payload, timeout=900)
                if response.status_code in [200, 302]:
                    uploaded_count += len(chunk)
                    end_row = current_target + len(chunk) - 1
                    print(
                        f"[GOOGLE SHEETS] Batch Sukses: Baris {current_target} s/d"
                        f" {end_row} | Progres: {uploaded_count}/{total_rows} baris"
                    )
                    current_target += len(chunk)
                    batch_success = True
                    break
                else:
                    print(
                        f"[ERROR GOOGLE SHEETS] Gagal mengunggah batch baris"
                        f" {current_target} (Status HTTP: {response.status_code}). Coba"
                        f" lagi ({attempt}/{max_retries})..."
                    )
            except Exception as e:
                print(
                    f"[ERROR GOOGLE SHEETS] Error koneksi pada batch baris"
                    f" {current_target}: {e}. Coba lagi ({attempt}/{max_retries})..."
                )

            time.sleep(3)

        if not batch_success:
            print(
                f"\n[FATAL GOOGLE SHEETS] Gagal mengunggah batch baris"
                f" {current_target} setelah {max_retries} kali percobaan."
            )
            break

    # 4. Verifikasi Akhir
    print("-" * 70)
    if uploaded_count == total_rows:
        print(
            f"[VERIFIKASI SUKSES] Total {total_rows} baris data BERHASIL di-copy ke"
            f" Google Sheets '{worksheet_name}'!"
        )
    else:
        print(
            f"[VERIFIKASI PARSIAL] Terkirim {uploaded_count} dari total {total_rows} baris."
        )


def fetch_single_chunk(
    session, chunks_url, job_id, unitup, chunk_idx, max_retries=3
):
    """Worker fungsi untuk mendownload 1 chunk secara independen."""
    c_params = {
        "jobId": str(job_id),
        "unitup": str(unitup),
        "chunkIndex": str(chunk_idx),
    }

    for attempt in range(1, max_retries + 1):
        try:
            c_res = session.get(
                chunks_url, params=c_params, timeout=60, verify=False
            )
            if c_res.status_code == 200:
                c_json = c_res.json()
                items = []

                if isinstance(c_json, dict):
                    data_inner = c_json.get("data")
                    if isinstance(data_inner, dict):
                        items = (
                            data_inner.get("data")
                            or data_inner.get("content")
                            or data_inner.get("items")
                            or []
                        )
                    elif isinstance(data_inner, list):
                        items = data_inner
                    else:
                        items = (
                            c_json.get("content")
                            or c_json.get("detail")
                            or c_json.get("items")
                            or []
                        )
                elif isinstance(c_json, list):
                    items = c_json

                if items:
                    for item in items:
                        if isinstance(item, dict):
                            item["UNITUP"] = str(unitup)
                print(f"[{unitup}] Chunk {chunk_idx} done: {len(items)} items")
                return chunk_idx, items

        except Exception:
            if attempt < max_retries:
                time.sleep(0.5)

    return chunk_idx, []


def scrape_detail_tunggakan_multi_unitup(list_unitup, output_filename=None):
    if output_filename is None:
        output_filename = get_default_output_filename()

    start_dt = datetime.now()
    start_datetime_str = start_dt.strftime("%d/%m/%Y %H:%M:%S")

    base_endpoint = "https://newap2t.pln.co.id/rtr-laporan/rtr-laporan-terpusat/data-tunggakan/get-detail"
    init_url = f"{base_endpoint}/init-chunks"
    status_url = f"{base_endpoint}/chunks/status"
    chunks_url = f"{base_endpoint}/chunks"

    if not output_filename.endswith(".xlsx"):
        output_filename = f"{output_filename.rsplit('.', 1)[0]}.xlsx"

    all_combined_data = []
    session = create_optimized_session(pool_size=MAX_CHUNK_WORKERS + 5)

    print("=" * 70)
    print(
        "Memulai Penarikan Data Detail Tunggakan (PARALEL) untuk"
        f" {len(list_unitup)} UNITUP"
    )
    print(f"Waktu Mulai    : {start_datetime_str}")
    print(f"Periode (THBL) : {THBL}")
    print(f"Daftar UNITUP  : {', '.join(list_unitup)}")
    print("=" * 70)

    for idx, unitup in enumerate(list_unitup, 1):
        print(f"\n>>> [{idx}/{len(list_unitup)}] Memproses UNITUP: {unitup} <<<")

        try:
            params = {
                "unitup": str(unitup),
                "thbl": str(THBL),
                "lembar1": "0",
                "lembar2": "3",
                "kogol": "X",
            }

            init_success = False
            job_id = None

            for retry_attempt in range(1, 6):
                if retry_attempt > 1:
                    print(f"[{unitup}] Retry inisialisasi attempt {retry_attempt}/5...")
                    time.sleep(2)

                init_res = session.post(
                    init_url, params=params, data="null", timeout=60, verify=False
                )

                if init_res.status_code not in [200, 201]:
                    print(
                        f"[{unitup}] Gagal inisialisasi job (attempt {retry_attempt}/5). Status: {init_res.status_code}"
                    )
                    if retry_attempt == 5:
                        print(f"[{unitup}] Gagal inisialisasi setelah 5 percobaan. Skip UNITUP ini.")
                        break
                    continue

                init_json = init_res.json()
                data_obj = init_json.get("data", {})

                job_id = (
                    data_obj.get("jobId")
                    if isinstance(data_obj, dict)
                    else (
                        data_obj
                        if isinstance(data_obj, str)
                        else init_json.get("jobId")
                    )
                )

                if not job_id:
                    print(f"[{unitup}] Gagal mendapatkan jobId (attempt {retry_attempt}/5).")
                    if retry_attempt == 5:
                        print(f"[{unitup}] Gagal mendapatkan jobId setelah 5 percobaan. Skip UNITUP ini.")
                        break
                    continue

                init_success = True
                if retry_attempt > 1:
                    print(f"[{unitup}] Inisialisasi berhasil pada attempt {retry_attempt}")
                break

            if not init_success or not job_id:
                continue

            status_params = {"jobId": str(job_id), "unitup": str(unitup)}
            total_chunks, total_rows, is_ready = 0, 0, False

            for _ in range(60):
                time.sleep(1.5)
                stat_res = session.get(
                    status_url, params=status_params, timeout=30, verify=False
                )
                if stat_res.status_code == 200:
                    stat_data = stat_res.json().get("data", {})
                    if stat_data.get("status") == "READY":
                        is_ready = True
                        total_chunks = stat_data.get("totalChunks", 0)
                        total_rows = stat_data.get("totalRows", 0)
                        print(
                            f"[{unitup}] Status READY! Total Baris: {total_rows} | Total Chunks: {total_chunks}"
                        )
                        break

            if not is_ready or total_chunks == 0:
                print(f"[{unitup}] Timeout atau data kosong.")
                continue

            unitup_items = []
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=MAX_CHUNK_WORKERS
            ) as executor:
                future_to_chunk = {
                    executor.submit(
                        fetch_single_chunk, session, chunks_url, job_id, unitup, c_idx
                    ): c_idx
                    for c_idx in range(total_chunks)
                }

                chunk_results = {}
                for future in concurrent.futures.as_completed(future_to_chunk):
                    c_idx, items = future.result()
                    chunk_results[c_idx] = items

            for c_idx in range(total_chunks):
                unitup_items.extend(chunk_results.get(c_idx, []))

            all_combined_data.extend(unitup_items)
            print(f"[{unitup}] Selesai mengunduh {len(unitup_items)} baris.")
            time.sleep(3)

        except Exception as e:
            print(f"[{unitup}] Error pada proses UNITUP: {e}")

    # ==========================================================================
    # PENGOLAHAN DATA, DEDUPLIKASI & TIMESTAMP LOOKER STUDIO
    # ==========================================================================
    if all_combined_data:
        print("\n" + "=" * 70)
        print("[PROSES DATA] Mengonversi data, membersihkan duplikat, merapikan kolom...")

        df = pd.DataFrame(all_combined_data)
        raw_count = len(df)

        df = df.drop_duplicates().reset_index(drop=True)
        dedup_count = len(df)
        print(f"[PEMBERSIHAN DATA] Total ditarik      : {raw_count} baris")
        print(
            f"[PEMBERSIHAN DATA] Setelah deduplikasi: {dedup_count} baris (Dibuang: {raw_count - dedup_count} duplikat)"
        )

        df = drop_specified_columns(df, COLS_TO_DROP)
        df = reorder_columns(df)
        df = format_date_columns(df)

        execution_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        df["LAST_UPDATE"] = execution_timestamp
        print(f"[LOOKER STUDIO] Menambahkan kolom 'LAST_UPDATE': {execution_timestamp}")

        try:
            os.makedirs(os.path.dirname(os.path.abspath(output_filename)), exist_ok=True)
            df.to_excel(output_filename, index=False, engine="openpyxl")
            print(
                f"[EXCEL SUKSES] Disimpan ke local file: '{output_filename}' ({len(df)} baris)"
            )
        except Exception as e:
            print(f"[EXCEL ERROR] Gagal menyimpan file Excel: {e}")

        push_to_google_sheets(
            df=df,
            web_app_url=WEB_APP_URL,
            worksheet_name=WORKSHEET_NAME,
            start_target_row=TARGET_ROW,
            chunk_size=8000,
            max_retries=5,
        )
    else:
        print("\n[PERINGATAN] Tidak ada data yang berhasil ditarik dari semua UNITUP.")

    end_datetime_str = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    print("\n" + "=" * 70)
    print(" SELURUH PROSES SELESAI!")
    print(f" • Waktu Mulai           : {start_datetime_str}")
    print(f" • Waktu Selesai         : {end_datetime_str}")
    print(
        f" • Total Data Gabungan   : {len(all_combined_data) if all_combined_data else 0} baris"
    )
    print("=" * 70)

    return all_combined_data


if __name__ == "__main__":
    acquire_lock()
    try:
        scrape_detail_tunggakan_multi_unitup(LIST_UNITUP)
    finally:
        release_lock()
