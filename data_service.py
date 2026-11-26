import csv
import io
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import pandas as pd
import requests

SPREADSHEET_ID = os.environ.get(
    "GSHEETS_ID", "1Y23fh3aMdQNHGyqZncsAdDpsMT15K6Z0niCbfuUJnH0"
)

SHEET_GIDS = {
    "DETILTUNGGAKAN": "381961518",
    "SALDOHARIAN": "1439657489",
    "DATA_MASTER": "1986186756",
    "MASTER_BILLER": "812000972",
    "MASTER_PEMDA": "2034467338",
    "KINERJA": "1580277993",
    "TARGET": "1164895927",
    "PEMUTUSAN": "992227843",
}

UNIT_LABELS = {
    "32111": "32111 - PANAKUKKANG",
    "32121": "32121 - MATTOTANGING",
    "32131": "32131 - SUNGGUMINASA",
    "32141": "32141 - KALEBAJENG",
    "32151": "32151 - TAKALAR",
    "32161": "32161 - MALINO",
}

UNIT_SHORT = {
    "32111": "PANAKUKKANG",
    "32121": "MATTOTANGING",
    "32131": "SUNGGUMINASA",
    "32141": "KALEBAJENG",
    "32151": "TAKALAR",
    "32161": "MALINO",
}

PEMDA_DEFAULT = {
    "1A": "MAKASSAR",
    "1B": "GOWA",
    "1C": "TAKALAR",
    "1D": "MAROS",
    "7B": "JENEPONTO",
}

TARGET_UNIT_JUTA = {
    "32111": 91.0,
    "32121": 161.0,
    "32131": 180.0,
    "32141": 22.0,
    "32151": 141.0,
    "32161": 5.0,
}

TARGET_UP3_RP = 600_000_000.0


def parse_id_number(val):
    """Parse Indonesian or standard formatted numbers (e.g. 'Rp32.529.799', '91,00', '3752562')."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    if not s or s in ("-", "null", "None", "nan", "NaN"):
        return 0.0
    s = re.sub(r"(?i)^rp\.?\s*", "", s).replace(" ", "")
    # Indonesian style: 1.234.567,89 or 91,00
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        # Check if comma is decimal (1-2 digits after comma) vs thousand sep
        parts = s.split(",")
        if len(parts) == 2 and len(parts[1]) <= 2:
            s = s.replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "." in s:
        parts = s.split(".")
        if len(parts) > 2 or (len(parts) == 2 and len(parts[1]) == 3):
            s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return 0.0


def classify_segmen_tarif(tarif):
    t = str(tarif or "").strip().upper()
    if t.startswith("R"):
        return "Rumah Tangga"
    if t.startswith("B"):
        return "Bisnis"
    if t.startswith("I"):
        return "Industri"
    if t.startswith("S"):
        return "Sosial"
    if t.startswith("P"):
        return "Pemerintah"
    if t.startswith("T") or t.startswith("C") or t.startswith("L"):
        return "Khusus / Lainnya"
    return "Lainnya"


def normalize_unit_code(val):
    s = str(val or "").strip()
    m = re.search(r"(321[1-6]1)", s)
    return m.group(1) if m else s


class DashboardDataService:
    def __init__(self, project_dir):
        self.project_dir = project_dir
        self.cache_dir = os.path.join(project_dir, "data", "cache")
        os.makedirs(self.cache_dir, exist_ok=True)
        self._lock = threading.Lock()
        self._sheets = {}
        self._source_mode = "uninitialized"
        self._fetched_at = None
        self._last_error = None
        self._cache_ttl = 300  # 5 minutes

    def _csv_url(self, gid):
        return (
            f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}"
            f"/export?format=csv&gid={gid}"
        )

    def _fetch_single_sheet(self, name, gid):
        url = self._csv_url(gid)
        resp = requests.get(url, timeout=25)
        resp.raise_for_status()
        text = resp.content.decode("utf-8-sig", errors="replace")
        # Save CSV cache
        cache_path = os.path.join(self.cache_dir, f"{name}.csv")
        with open(cache_path, "w", encoding="utf-8") as f:
            f.write(text)
        df = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False)
        return name, df

    def _load_from_disk_cache(self):
        loaded = {}
        for name in SHEET_GIDS:
            cache_path = os.path.join(self.cache_dir, f"{name}.csv")
            if os.path.isfile(cache_path):
                try:
                    loaded[name] = pd.read_csv(
                        cache_path, dtype=str, keep_default_na=False
                    )
                except Exception:
                    pass
        return loaded

    def _load_local_excel_fallback(self):
        candidates = [
            os.path.join(self.project_dir, "data", "gabungan_detail_tunggakan.xlsx"),
            r"D:\BOT\gabungan_detail_tunggakan.xlsx",
        ]
        for path in candidates:
            if os.path.isfile(path):
                try:
                    return pd.read_excel(path, dtype=str).fillna("")
                except Exception:
                    pass
        return None

    def _build_offline_snapshot(self):
        """Fallback snapshot accurately reflecting SALDO TUNGGAKAN AMS structure when offline."""
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        detil_rows = [
            ("32121", "321409142643", "UNIV INDONESIA TIMUR", "JL ABD KADIR NO 048", "JBAAMG", "1A", "S2K", "1385000", "0", "1", "113872668", now_str),
            ("32151", "321510345939", "KOPERASI ALHAMIDI", "DS LAMBUTOA PA'LALAKKANG GALESONG", "JEDGLE", "1C", "I2", "66000", "0", "1", "39796017", now_str),
            ("32161", "321310143819", "PT. HARFIA GRAHA PERKASA", "JL POROS MALINO KP KASSI P.LOE GOWA", "JFAAMG", "1B", "I3", "690000", "0", "1", "35158533", now_str),
            ("32151", "321510014703", "PABRIK ES DINAS KEL", "KP PPI BEBA GALESONG TAKALAR", "JEAAMG", "1C", "I2", "66000", "0", "1", "31015789", now_str),
            ("32141", "321410113758", "RS PRATAMA GOWA", "DS JL POROS BONTONOMPO", "JDAAMR", "1B", "S1", "105000", "0", "1", "21064500", now_str),
            ("32111", "321202684113", "RSIA BAHAGIA", "KK MINASA UPA RUMKIT NO 5", "JAAAMT", "1A", "B2", "105000", "0", "1", "20071217", now_str),
            ("32161", "321610153681", "SARI HARDIAYANTI MS", "JL POROS ALLUKEKE", "JFAAMT", "1B", "I2", "41500", "0", "1", "18280745", now_str),
            ("32151", "321510244190", "SUDIRMAN, S.PD M.ED", "DN TOMBOLO BONTOMANAI MARBO", "JEAAMG", "1C", "I2", "82500", "0", "3", "9622800", now_str),
            ("32161", "321610104104", "MUSTAKIM", "DS BELAPUNRANGA SUNGGUMINASA", "JFAAMT", "1B", "I2", "82500", "0", "1", "9079853", now_str),
            ("32121", "321210342338", "FACHRUDDIN", "JL WIJAYA KUSUMA 3", "JBAAMT", "1A", "B2", "23000", "0", "1", "9065493", now_str),
            ("32131", "321310291044", "HOTEL PURI GOWA", "JL SULTAN HASANUDDIN NO 12", "JCAAMT", "1B", "B2", "53000", "0", "1", "16450000", now_str),
            ("32131", "321310884312", "CV KARYA MANDIRI", "JL POROS PALLANGGA NO 88", "JCAAMT", "1B", "I2", "41500", "0", "2", "14280500", now_str),
            ("32131", "321310441209", "DINAS KESEHATAN GOWA", "JL MESJID RAYA SUNGGUMINASA", "JCAAMT", "1B", "P1", "33000", "3", "2", "18726408", now_str),
            ("32131", "321310441299", "KANTOR BUPATI GOWA LAMP", "JL MASJID RAYA NO 30 GOWA", "JCAAMT", "1B", "P1", "66000", "3", "1", "18000000", now_str),
            ("32151", "321510772310", "KANTOR CAMAT GALESONG", "JL POROS GALESONG TAKALAR", "JEDGLE", "1C", "P1", "10600", "3", "2", "9502640", now_str),
            ("32141", "321410551022", "PUSKESMAS JENEPONTO PERBATASAN", "JL POROS JENEPONTO", "JDAAMR", "7B", "P1", "5500", "3", "1", "218265", now_str),
            ("32111", "320100080878", "TRUNKING SPN BATUA", "JL URIP SUMOHARJO NO 0", "JAAAMT", "1A", "P1", "6600", "1", "2", "3752562", now_str),
            ("32111", "320100093858", "SALEH 01", "JL INSPEKSI WADUK BORONG", "JAAPKR", "1A", "B1", "5500", "0", "1", "266200", now_str),
            ("32111", "320100093866", "SALEH 02", "JL INSPEKSI WADUK BORONG", "JAAPKR", "1A", "B1", "2200", "0", "2", "347270", now_str),
            ("32111", "320100123065", "HATIJAH", "JL PACCINANG RAYA NO 39A", "JAAMGB", "1A", "R1M", "900", "0", "3", "455083", now_str),
            ("32121", "321210112233", "TNI AL MATTOTANGING", "JL MALENGKERI RAYA", "JBAAMT", "1A", "P1", "41500", "2", "1", "29048000", now_str),
            ("32131", "321310998877", "KODIM 1409 GOWA", "JL SULTAN HASANUDDIN", "JCAAMT", "1B", "P1", "23000", "2", "1", "20000000", now_str),
            ("32121", "321210554433", "TOKO SINAR MATTOTANGING", "JL DAENG TATA NO 15", "JBAAMT", "1A", "B1", "5500", "0", "2", "4250000", now_str),
            ("32121", "321210554499", "RUMAH MAKAN PANGKEP", "JL ALAUDDIN NO 91", "JBAAMT", "1A", "B2", "13200", "0", "3", "6120000", now_str),
            ("32131", "321310665544", "PERUMAHAN CITRA GOWA", "JL TUN ABDUL RAZAK", "JCAAMT", "1B", "R2", "3500", "0", "3", "5430000", now_str),
            ("32141", "321410887766", "H. SYAMSUDDIN", "JL POROS LIMBUNG KALEBAJENG", "JDAAMR", "1B", "R1", "1300", "0", "1", "1850000", now_str),
            ("32151", "321510664422", "UD TAKALAR JAYA", "JL JEND SUDIRMAN TAKALAR", "JEDGLE", "1C", "B2", "16500", "0", "2", "7890000", now_str),
        ]
        detil_df = pd.DataFrame(
            detil_rows,
            columns=[
                "unitap", "idpel", "nama", "alamat", "rbm", "kdpemda",
                "tarif", "daya", "kogol", "lembar", "rpptl", "LastUpdate",
            ],
        )
        detil_df["unitup"] = "32AMS"
        detil_df["KodeUnit"] = detil_df["unitap"]
        detil_df["rptag"] = detil_df["rpptl"]

        # SALDOHARIAN demo (Oct & Nov 2026)
        harian_rows = []
        base_units = {
            "32111": 800_000_000,
            "32121": 1_850_000_000,
            "32131": 2_770_000_000,
            "32141": 545_000_000,
            "32151": 1_475_000_000,
            "32161": 120_000_000,
        }
        for month_prefix, factor in [("202610", 0.94), ("202611", 1.0)]:
            max_day = 31 if month_prefix == "202610" else 25
            for d in range(1, max_day + 1):
                decay = max(0.18, 2.2 - (d * 0.055))
                for u, base_rp in base_units.items():
                    rp = int(base_rp * factor * decay)
                    lbr = max(10, int((rp / 230_000)))
                    harian_rows.append({
                        "NAMA ULP": UNIT_LABELS[u],
                        "ULP": u,
                        "Tanggal": f"{month_prefix}{d:02d}",
                        "Status": "L",
                        "Golongan": "0",
                        "Lembar": str(lbr),
                        "Rp PTL": str(rp),
                        "Rp Tagihan": str(int(rp * 1.08)),
                    })
        harian_df = pd.DataFrame(harian_rows)

        master_df = pd.DataFrame([
            {"UNIT": k, "ULP": UNIT_SHORT[k], "PREFIX": v}
            for k, v in UNIT_LABELS.items()
        ])
        biller_df = pd.DataFrame([
            {"KODE RBM": "JAAAMT", "NAMA_ULP": "32111-PANAKKUKANG", "NAMA": "ACHYAR"},
            {"KODE RBM": "JAAPKR", "NAMA_ULP": "32111-PANAKKUKANG", "NAMA": "MULIADI"},
            {"KODE RBM": "JAAMGB", "NAMA_ULP": "32111-PANAKKUKANG", "NAMA": "AKBAR"},
            {"KODE RBM": "JBAAMG", "NAMA_ULP": "32121-MATTOTANGING", "NAMA": "KOORD MTG"},
            {"KODE RBM": "JBAAMT", "NAMA_ULP": "32121-MATTOTANGING", "NAMA": "SYARIFUDDIN"},
            {"KODE RBM": "JCAAMT", "NAMA_ULP": "32131-SUNGGUMINASA", "NAMA": "KOORD SGM"},
            {"KODE RBM": "JDAAMR", "NAMA_ULP": "32141-KALEBAJENG", "NAMA": "RAHMAT"},
            {"KODE RBM": "JEDGLE", "NAMA_ULP": "32151-TAKALAR", "NAMA": "ASWAN"},
            {"KODE RBM": "JEAAMG", "NAMA_ULP": "32151-TAKALAR", "NAMA": "HENDRA"},
            {"KODE RBM": "JFAAMG", "NAMA_ULP": "32161-MALINO", "NAMA": "RIDWAN"},
            {"KODE RBM": "JFAAMT", "NAMA_ULP": "32161-MALINO", "NAMA": "IRWAN"},
        ])
        pemda_df = pd.DataFrame([
            {"KODE_PEMDA": k, "PEMDA": v} for k, v in PEMDA_DEFAULT.items()
        ])
        kinerja_rows = []
        for m in range(1, 12):
            for u, tgt in TARGET_UNIT_JUTA.items():
                real = round(tgt * (0.75 + (m % 4) * 0.14), 2)
                prr_tgt = round(tgt * 350_000, 0)
                prr_real = round(prr_tgt * (0.8 + (m % 3) * 0.12), 0)
                kinerja_rows.append({
                    "PERIODE": f"01/{m:02d}/2026",
                    "ULP": UNIT_LABELS[u],
                    "KODE": f"ULP {UNIT_SHORT[u]}",
                    "TARGET SALDO PIUTANG": str(tgt),
                    "REALISASI SALDO PIUTANG": str(real),
                    "TARGET PRR": str(int(prr_tgt)),
                    "1. PRR": str(int(prr_real * 0.5)),
                    "2. EX-PRR (AP2T)": str(int(prr_real * 0.15)),
                    "3. PRABAYAR": str(int(prr_real * 0.35)),
                    "REALISASI TOTAL PRR": str(int(prr_real)),
                    "TARGET TRANSAKSI": "12000",
                    "REALISASI TRANSAKSI": str(int(10500 + m * 210)),
                })
        kinerja_df = pd.DataFrame(kinerja_rows)
        return {
            "DETILTUNGGAKAN": detil_df,
            "SALDOHARIAN": harian_df,
            "DATA_MASTER": master_df,
            "MASTER_BILLER": biller_df,
            "MASTER_PEMDA": pemda_df,
            "KINERJA": kinerja_df,
        }

    def ensure_loaded(self, force=False):
        with self._lock:
            now = time.time()
            if (
                not force
                and self._sheets
                and self._fetched_at
                and (now - self._fetched_at) < self._cache_ttl
            ):
                return self._sheets

            fetched = {}
            errors = []
            with ThreadPoolExecutor(max_workers=6) as ex:
                futures = {
                    ex.submit(self._fetch_single_sheet, name, gid): name
                    for name, gid in SHEET_GIDS.items()
                }
                for fut in as_completed(futures):
                    name = futures[fut]
                    try:
                        _, df = fut.result()
                        fetched[name] = df
                    except Exception as e:
                        errors.append(f"{name}: {e}")

            if "DETILTUNGGAKAN" in fetched and len(fetched["DETILTUNGGAKAN"]) > 0:
                self._sheets = fetched
                self._source_mode = "live_google_sheets"
                self._fetched_at = now
                self._last_error = None
                return self._sheets

            # Fallback 1: Disk cache CSVs
            disk = self._load_from_disk_cache()
            if "DETILTUNGGAKAN" in disk and len(disk["DETILTUNGGAKAN"]) > 0:
                self._sheets = disk
                self._source_mode = "disk_cache"
                self._fetched_at = now
                self._last_error = "; ".join(errors[:2]) if errors else None
                return self._sheets

            # Fallback 2: Local Excel + offline demo companion sheets
            snapshot = self._build_offline_snapshot()
            local_xl = self._load_local_excel_fallback()
            if local_xl is not None and len(local_xl) > 0:
                snapshot["DETILTUNGGAKAN"] = local_xl
                self._source_mode = "local_excel"
            else:
                self._source_mode = "offline_snapshot"

            self._sheets = snapshot
            self._fetched_at = now
            self._last_error = "; ".join(errors[:2]) if errors else None
            return self._sheets

    def _prepare_detil_df(self, raw_df):
        if raw_df is None or len(raw_df) == 0:
            return pd.DataFrame()
        df = raw_df.copy()
        col_map = {c.lower().strip(): c for c in df.columns}

        def get_col(candidates, default=""):
            for cand in candidates:
                if cand in col_map:
                    return df[col_map[cand]].astype(str).str.strip()
            return pd.Series([default] * len(df), index=df.index)

        out = pd.DataFrame(index=df.index)
        # In DETILTUNGGAKAN, unitap or KodeUnit holds 32111..32161
        unit_series = get_col(["kodeunit", "unitap", "unitup", "ulp", "unit"])
        out["ulp"] = unit_series.apply(normalize_unit_code)
        out["idpel"] = get_col(["idpel"])
        out["nama"] = get_col(["nama"])
        out["alamat"] = get_col(["alamat"])
        out["rbm"] = get_col(["rbm"])
        out["kdpemda"] = get_col(["kdpemda", "kode_pemda"])
        out["tarif"] = get_col(["tarif"])
        out["daya"] = get_col(["daya"]).apply(lambda x: int(parse_id_number(x)))
        out["kogol"] = get_col(["kogol"])
        out["lembar"] = get_col(["lembar"]).apply(lambda x: int(parse_id_number(x)))
        out["rpptl"] = get_col(["rpptl", "rp_ptl"]).apply(parse_id_number)
        out["rptag"] = get_col(["rptag", "rp_tagihan"]).apply(parse_id_number)
        out["last_update"] = get_col(["lastupdate", "last_update"])
        out["segmen_tarif"] = out["tarif"].apply(classify_segmen_tarif)
        # Drop completely empty rows
        out = out[out["idpel"].str.len() > 0].copy()
        return out

    def get_cashin_payload(self, params):
        sheets = self.ensure_loaded(force=params.get("refresh") == "1")
        detil_raw = sheets.get("DETILTUNGGAKAN")
        detil = self._prepare_detil_df(detil_raw)

        # Scope toggle: Non Kogol 1,2 dan KTT (default true to match Looker Studio)
        non_kogol_12 = params.get("non_kogol_12", "1") != "0"

        # Master maps
        pemda_map = dict(PEMDA_DEFAULT)
        pemda_df = sheets.get("MASTER_PEMDA")
        if pemda_df is not None and len(pemda_df) > 0:
            c0, c1 = pemda_df.columns[0], pemda_df.columns[1]
            for _, row in pemda_df.iterrows():
                k = str(row[c0]).strip()
                v = str(row[c1]).strip()
                if k:
                    pemda_map[k] = v

        biller_map = {}
        biller_df = sheets.get("MASTER_BILLER")
        if biller_df is not None and len(biller_df) >= 1 and len(biller_df.columns) >= 3:
            c_rbm, c_ulp, c_nama = biller_df.columns[0], biller_df.columns[1], biller_df.columns[2]
            for _, row in biller_df.iterrows():
                rbm_k = str(row[c_rbm]).strip().upper()
                if rbm_k:
                    biller_map[rbm_k] = str(row[c_nama]).strip()

        # Filter options (from full dataset before user filters)
        def uniq_sorted(series, numeric=False):
            vals = [v for v in series.dropna().unique().tolist() if str(v).strip() != ""]
            if numeric:
                return sorted(vals, key=lambda x: float(x))
            return sorted([str(v) for v in vals])

        filter_options = {
            "ulp": [{"value": u, "label": UNIT_LABELS.get(u, u)} for u in sorted(UNIT_LABELS.keys())],
            "rbm": uniq_sorted(detil["rbm"]) if len(detil) else [],
            "lembar": uniq_sorted(detil["lembar"], numeric=True) if len(detil) else [],
            "kogol": uniq_sorted(detil["kogol"]) if len(detil) else [],
            "segmen_tarif": uniq_sorted(detil["segmen_tarif"]) if len(detil) else [],
            "tarif": uniq_sorted(detil["tarif"]) if len(detil) else [],
            "daya": uniq_sorted(detil["daya"], numeric=True) if len(detil) else [],
        }

        # Apply global scope (Saldo Non Kogol 1,2) to primary view, keep full for SALDO PER KOGOL
        scoped = detil.copy()
        if non_kogol_12 and len(scoped):
            scoped = scoped[~scoped["kogol"].isin(["1", "2"])]

        # Apply interactive filters
        filtered = scoped.copy()
        if len(filtered):
            if params.get("ulp"):
                filtered = filtered[filtered["ulp"] == params["ulp"]]
            if params.get("rbm"):
                filtered = filtered[filtered["rbm"] == params["rbm"]]
            if params.get("lembar"):
                try:
                    filtered = filtered[filtered["lembar"] == int(params["lembar"])]
                except ValueError:
                    pass
            if params.get("kogol"):
                # If user explicitly picked kogol 1 or 2, filter from full detil
                if params["kogol"] in ("1", "2") and non_kogol_12:
                    filtered = detil[detil["kogol"] == params["kogol"]].copy()
                    if params.get("ulp"):
                        filtered = filtered[filtered["ulp"] == params["ulp"]]
                else:
                    filtered = filtered[filtered["kogol"] == params["kogol"]]
            if params.get("segmen_tarif"):
                filtered = filtered[filtered["segmen_tarif"] == params["segmen_tarif"]]
            if params.get("tarif"):
                filtered = filtered[filtered["tarif"] == params["tarif"]]
            if params.get("daya"):
                try:
                    filtered = filtered[filtered["daya"] == int(params["daya"])]
                except ValueError:
                    pass
            if params.get("saldo_val"):
                try:
                    sv = parse_id_number(params["saldo_val"])
                    op = params.get("saldo_op", "eq")
                    if op == "eq":
                        filtered = filtered[filtered["rpptl"] == sv]
                    elif op == "gt":
                        filtered = filtered[filtered["rpptl"] > sv]
                    elif op == "gte":
                        filtered = filtered[filtered["rpptl"] >= sv]
                    elif op == "lt":
                        filtered = filtered[filtered["rpptl"] < sv]
                    elif op == "lte":
                        filtered = filtered[filtered["rpptl"] <= sv]
                except Exception:
                    pass
            if params.get("search"):
                q = params["search"].strip().lower()
                mask = (
                    filtered["idpel"].str.lower().str.contains(q, na=False)
                    | filtered["nama"].str.lower().str.contains(q, na=False)
                    | filtered["alamat"].str.lower().str.contains(q, na=False)
                    | filtered["rbm"].str.lower().str.contains(q, na=False)
                )
                filtered = filtered[mask]

        # Last update timestamp
        last_update = "-"
        if len(detil) and "last_update" in detil.columns:
            non_empty_lu = detil["last_update"][detil["last_update"].str.len() > 0]
            if len(non_empty_lu):
                last_update = str(non_empty_lu.iloc[0])

        # 1. KPIs
        kpi = {
            "saldo_saat_ini": float(filtered["rpptl"].sum()) if len(filtered) else 0.0,
            "total_pelanggan": int(len(filtered)),
            "total_lembar": int(filtered["lembar"].sum()) if len(filtered) else 0,
            "target_up3": TARGET_UP3_RP,
            "last_update": last_update,
            "scope_label": "Saldo Non Kogol 1,2 dan KTT" if non_kogol_12 else "Semua Kogol (Termasuk Kogol 1 & 2)",
        }

        # 2. SALDO UNIT (Pivot UNIT x Lembar 1, 2, 3, UP3)
        saldo_unit_rows = []
        totals = {1: {"plg": 0, "rp": 0.0}, 2: {"plg": 0, "rp": 0.0}, 3: {"plg": 0, "rp": 0.0}, "up3": {"plg": 0, "rp": 0.0}}
        for unit_code in sorted(UNIT_LABELS.keys()):
            sub = filtered[filtered["ulp"] == unit_code] if len(filtered) else pd.DataFrame()
            row = {"unit": unit_code, "unit_name": UNIT_SHORT.get(unit_code, unit_code)}
            for lbr in (1, 2, 3):
                if len(sub):
                    lsub = sub[sub["lembar"] == lbr] if lbr < 3 else sub[sub["lembar"] >= 3]
                    plg_c = int(len(lsub))
                    rp_c = float(lsub["rpptl"].sum())
                else:
                    plg_c, rp_c = 0, 0.0
                row[f"l{lbr}_plg"] = plg_c
                row[f"l{lbr}_rp"] = rp_c
                totals[lbr]["plg"] += plg_c
                totals[lbr]["rp"] += rp_c
            up3_plg = int(len(sub))
            up3_rp = float(sub["rpptl"].sum()) if len(sub) else 0.0
            row["up3_plg"] = up3_plg
            row["up3_rp"] = up3_rp
            totals["up3"]["plg"] += up3_plg
            totals["up3"]["rp"] += up3_rp
            saldo_unit_rows.append(row)

        saldo_unit_total = {
            "unit": "UP3",
            "unit_name": "UP3 MAKASSAR SELATAN",
            "l1_plg": totals[1]["plg"], "l1_rp": totals[1]["rp"],
            "l2_plg": totals[2]["plg"], "l2_rp": totals[2]["rp"],
            "l3_plg": totals[3]["plg"], "l3_rp": totals[3]["rp"],
            "up3_plg": totals["up3"]["plg"], "up3_rp": totals["up3"]["rp"],
        }

        # 3. SALDO PER KOGOL (shows all non-1 kogols or all kogols)
        kogol_src = detil.copy()
        if params.get("ulp"):
            kogol_src = kogol_src[kogol_src["ulp"] == params["ulp"]]
        if non_kogol_12:
            kogol_src = kogol_src[kogol_src["kogol"] != "1"]
        saldo_kogol = []
        if len(kogol_src):
            grp = kogol_src.groupby("kogol", as_index=False).agg(
                plg=("idpel", "count"),
                rp_ptl=("rpptl", "sum"),
            )
            grp = grp.sort_values("kogol", ascending=False)
            for _, r in grp.iterrows():
                saldo_kogol.append({
                    "kogol": str(r["kogol"]),
                    "plg": int(r["plg"]),
                    "rp_ptl": float(r["rp_ptl"]),
                })
        saldo_kogol_total = {
            "plg": sum(x["plg"] for x in saldo_kogol),
            "rp_ptl": sum(x["rp_ptl"] for x in saldo_kogol),
        }

        # 4. LIST DATA DETIL PELANGGAN (paginated & sorted)
        sort_by = params.get("sort_by", "rpptl")
        if sort_by not in ("ulp", "idpel", "nama", "tarif", "daya", "rbm", "lembar", "rpptl"):
            sort_by = "rpptl"
        sort_asc = params.get("sort_dir", "desc").lower() == "asc"
        page = max(1, int(params.get("page", 1)))
        page_size = min(200, max(10, int(params.get("page_size", 50))))

        detail_sorted = filtered.sort_values(sort_by, ascending=sort_asc) if len(filtered) else filtered
        total_rows = int(len(detail_sorted))
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        page_slice = detail_sorted.iloc[start_idx:end_idx]

        detail_rows = []
        for idx_i, (_, r) in enumerate(page_slice.iterrows(), start=start_idx + 1):
            detail_rows.append({
                "no": idx_i,
                "ulp": r["ulp"],
                "idpel": r["idpel"],
                "nama": r["nama"],
                "alamat": r["alamat"],
                "tarif": r["tarif"],
                "daya": int(r["daya"]),
                "rbm": r["rbm"],
                "lembar": int(r["lembar"]),
                "rpptl": float(r["rpptl"]),
                "kogol": r["kogol"],
                "segmen_tarif": r["segmen_tarif"],
            })

        # 5. KOMPOSISI TUNGGAKAN PER TARIF
        komposisi_tarif = []
        if len(filtered):
            kt = filtered.groupby("tarif", as_index=False).agg(
                plg=("idpel", "count"),
                rp_ptl=("rpptl", "sum"),
            ).sort_values("rp_ptl", ascending=False).head(10)
            for _, r in kt.iterrows():
                komposisi_tarif.append({
                    "tarif": str(r["tarif"]) or "Lainnya",
                    "plg": int(r["plg"]),
                    "rp_ptl": float(r["rp_ptl"]),
                })

        # 6. KOMPOSISI TUNGGAKAN PER UNIT
        komposisi_unit = [
            {
                "unit": row["unit"],
                "label": UNIT_LABELS.get(row["unit"], row["unit"]),
                "short": row["unit_name"],
                "plg": row["up3_plg"],
                "rp_ptl": row["up3_rp"],
            }
            for row in saldo_unit_rows
        ]

        # 7. SALDO KOGOL 3 PER PEMDA
        kogol3_src = detil[detil["kogol"] == "3"].copy() if len(detil) else pd.DataFrame()
        if params.get("ulp") and len(kogol3_src):
            kogol3_src = kogol3_src[kogol3_src["ulp"] == params["ulp"]]
        saldo_pemda = []
        if len(kogol3_src):
            kogol3_src["pemda_nama"] = kogol3_src["kdpemda"].apply(
                lambda x: pemda_map.get(str(x).strip(), str(x).strip() or "LAINNYA")
            )
            pm = kogol3_src.groupby("pemda_nama", as_index=False).agg(
                plg=("idpel", "count"),
                rp_ptl=("rpptl", "sum"),
            ).sort_values("pemda_nama", ascending=True)
            for _, r in pm.iterrows():
                saldo_pemda.append({
                    "pemda": str(r["pemda_nama"]),
                    "plg": int(r["plg"]),
                    "rp_ptl": float(r["rp_ptl"]),
                })
        saldo_pemda_total = {
            "plg": sum(x["plg"] for x in saldo_pemda),
            "rp_ptl": sum(x["rp_ptl"] for x in saldo_pemda),
        }

        # 8. SALDO PER BILLER
        saldo_biller = []
        if len(filtered):
            bl = filtered.groupby(["ulp", "rbm"], as_index=False).agg(
                lembar=("lembar", "sum"),
                plg=("idpel", "count"),
                rp_ptl=("rpptl", "sum"),
            ).sort_values("rp_ptl", ascending=False).head(100)
            for idx_b, (_, r) in enumerate(bl.iterrows(), start=1):
                rbm_code = str(r["rbm"]).upper()
                saldo_biller.append({
                    "no": idx_b,
                    "ulp": str(r["ulp"]),
                    "rbm": str(r["rbm"]),
                    "nama": biller_map.get(rbm_code, "-"),
                    "lembar": int(r["lembar"]),
                    "plg": int(r["plg"]),
                    "rp_ptl": float(r["rp_ptl"]),
                })

        # 9. SALDOHARIAN: Grafik Penurunan Piutang, Tabel Perbandingan Tanggal, Tabel Perbandingan ULP
        trend_data, ulp_comp, ulp_comp_total, harian_meta = self._compute_saldoharian(
            sheets.get("SALDOHARIAN"),
            trend_ulp=params.get("trend_ulp", ""),
            trend_golongan=params.get("trend_golongan", ""),
            non_kogol_12=non_kogol_12,
        )

        return {
            "meta": {
                "source_mode": self._source_mode,
                "fetched_at": datetime.fromtimestamp(self._fetched_at).strftime("%d/%m/%Y %H:%M:%S")
                if self._fetched_at else "-",
                "last_error": self._last_error,
                "spreadsheet_url": f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit",
                "harian": harian_meta,
            },
            "kpi": kpi,
            "filter_options": filter_options,
            "saldo_unit": saldo_unit_rows,
            "saldo_unit_total": saldo_unit_total,
            "saldo_kogol": saldo_kogol,
            "saldo_kogol_total": saldo_kogol_total,
            "detail_pelanggan": {
                "rows": detail_rows,
                "page": page,
                "page_size": page_size,
                "total_rows": total_rows,
                "total_lembar": kpi["total_lembar"],
                "total_rpptl": kpi["saldo_saat_ini"],
            },
            "trend_comparison": trend_data,
            "ulp_comparison": ulp_comp,
            "ulp_comparison_total": ulp_comp_total,
            "komposisi_tarif": komposisi_tarif,
            "saldo_pemda": saldo_pemda,
            "saldo_pemda_total": saldo_pemda_total,
            "komposisi_unit": komposisi_unit,
            "saldo_biller": saldo_biller,
        }

    def _compute_saldoharian(self, raw_df, trend_ulp="", trend_golongan="", non_kogol_12=True):
        if raw_df is None or len(raw_df) == 0:
            return [], [], {}, {}

        df = raw_df.copy()
        cols = {c.lower().strip(): c for c in df.columns}
        c_ulp = cols.get("ulp") or cols.get("unit")
        c_tgl = cols.get("tanggal")
        c_gol = cols.get("golongan")
        c_lbr = cols.get("lembar")
        c_ptl = cols.get("rp ptl") or cols.get("rpptl")

        if not (c_ulp and c_tgl and c_ptl):
            return [], [], {}, {}

        work = pd.DataFrame({
            "ulp": df[c_ulp].apply(normalize_unit_code),
            "tanggal": df[c_tgl].astype(str).str.replace(r"\D", "", regex=True),
            "golongan": df[c_gol].astype(str).str.strip() if c_gol else "0",
            "lembar": df[c_lbr].apply(parse_id_number) if c_lbr else 0.0,
            "rp_ptl": df[c_ptl].apply(parse_id_number),
        })
        work = work[work["tanggal"].str.len() == 8].copy()
        if len(work) == 0:
            return [], [], {}, {}

        work["ym"] = work["tanggal"].str[:6]
        work["day"] = work["tanggal"].str[6:8].astype(int)

        if non_kogol_12 and not trend_golongan:
            work = work[~work["golongan"].isin(["1", "2"])]
        elif trend_golongan:
            work = work[work["golongan"] == trend_golongan]

        if trend_ulp:
            work_trend = work[work["ulp"] == trend_ulp]
        else:
            work_trend = work

        months = sorted(work["ym"].unique().tolist())
        curr_ym = months[-1]
        prev_ym = months[-2] if len(months) >= 2 else curr_ym

        curr_by_day = work_trend[work_trend["ym"] == curr_ym].groupby("day")["rp_ptl"].sum().to_dict()
        prev_by_day = work_trend[work_trend["ym"] == prev_ym].groupby("day")["rp_ptl"].sum().to_dict()

        trend_rows = []
        for d in range(1, 32):
            rp_lalu = float(prev_by_day.get(d, 0.0))
            rp_ini = float(curr_by_day.get(d, 0.0))
            if rp_lalu == 0.0 and rp_ini == 0.0:
                continue
            trend_rows.append({
                "tanggal": d,
                "rp_lalu": rp_lalu,
                "rp_ini": rp_ini,
                "selisih": rp_lalu - rp_ini,
            })

        # Latest day in current month (H-1) compared to same day in previous month
        curr_days = sorted(work[work["ym"] == curr_ym]["day"].unique().tolist())
        latest_day = curr_days[-1] if curr_days else 1

        curr_h1 = work[(work["ym"] == curr_ym) & (work["day"] == latest_day)]
        prev_h1 = work[(work["ym"] == prev_ym) & (work["day"] == latest_day)]

        ulp_comp = []
        tot_plg_lalu = tot_plg_h1 = 0.0
        tot_rp_lalu = tot_rp_h1 = 0.0
        for u in sorted(UNIT_LABELS.keys()):
            p_lalu = float(prev_h1[prev_h1["ulp"] == u]["lembar"].sum())
            r_lalu = float(prev_h1[prev_h1["ulp"] == u]["rp_ptl"].sum())
            p_h1 = float(curr_h1[curr_h1["ulp"] == u]["lembar"].sum())
            r_h1 = float(curr_h1[curr_h1["ulp"] == u]["rp_ptl"].sum())
            sel_p = p_lalu - p_h1
            sel_r = r_lalu - r_h1
            pct_p = (sel_p / p_lalu * 100.0) if p_lalu else 0.0
            pct_r = (sel_r / r_lalu * 100.0) if r_lalu else 0.0
            tot_plg_lalu += p_lalu
            tot_rp_lalu += r_lalu
            tot_plg_h1 += p_h1
            tot_rp_h1 += r_h1
            ulp_comp.append({
                "ulp": u,
                "unit_name": UNIT_SHORT.get(u, u),
                "plg_lalu": int(p_lalu),
                "rp_lalu": r_lalu,
                "plg_h1": int(p_h1),
                "rp_h1": r_h1,
                "selisih_plg": int(sel_p),
                "selisih_ptl": sel_r,
                "pct_plg": round(pct_p, 2),
                "pct_ptl": round(pct_r, 2),
            })

        tot_sel_p = tot_plg_lalu - tot_plg_h1
        tot_sel_r = tot_rp_lalu - tot_rp_h1
        ulp_comp_total = {
            "ulp": "UP3",
            "plg_lalu": int(tot_plg_lalu),
            "rp_lalu": tot_rp_lalu,
            "plg_h1": int(tot_plg_h1),
            "rp_h1": tot_rp_h1,
            "selisih_plg": int(tot_sel_p),
            "selisih_ptl": tot_sel_r,
            "pct_plg": round((tot_sel_p / tot_plg_lalu * 100.0) if tot_plg_lalu else 0.0, 2),
            "pct_ptl": round((tot_sel_r / tot_rp_lalu * 100.0) if tot_rp_lalu else 0.0, 2),
        }
        meta = {
            "curr_ym": curr_ym,
            "prev_ym": prev_ym,
            "latest_day": latest_day,
            "golongan_options": sorted(work["golongan"].unique().tolist()),
        }
        return trend_rows, ulp_comp, ulp_comp_total, meta

    def get_kinerja_payload(self, params):
        sheets = self.ensure_loaded(force=params.get("refresh") == "1")
        raw = sheets.get("KINERJA")
        if raw is None or len(raw) == 0:
            return {"meta": {"source_mode": self._source_mode}, "rows": [], "by_ulp": [], "by_periode": [], "kpi": {}}

        df = raw.copy()
        cols = {c.upper().strip(): c for c in df.columns}

        def col(name):
            return df[cols[name]] if name in cols else pd.Series([""] * len(df))

        work = pd.DataFrame({
            "periode": col("PERIODE").astype(str).str.strip(),
            "ulp": col("ULP").astype(str).str.strip(),
            "unit_code": col("ULP").apply(normalize_unit_code),
            "kode": col("KODE").astype(str).str.strip(),
            "target_saldo": col("TARGET SALDO PIUTANG").apply(parse_id_number),
            "realisasi_saldo": col("REALISASI SALDO PIUTANG").apply(parse_id_number),
            "target_prr": col("TARGET PRR").apply(parse_id_number),
            "prr_1": col("1. PRR").apply(parse_id_number),
            "ex_prr": col("2. EX-PRR (AP2T)").apply(parse_id_number),
            "prabayar": col("3. PRABAYAR").apply(parse_id_number),
            "realisasi_prr": col("REALISASI TOTAL PRR").apply(parse_id_number),
            "target_transaksi": col("TARGET TRANSAKSI").apply(parse_id_number),
            "realisasi_transaksi": col("REALISASI TRANSAKSI").apply(parse_id_number),
        })
        work = work[work["periode"].str.len() > 0].copy()

        periodes = work["periode"].drop_duplicates().tolist()
        selected_periode = params.get("periode", "")
        selected_ulp = params.get("ulp", "")

        filtered = work.copy()
        if selected_periode:
            filtered = filtered[filtered["periode"] == selected_periode]
        if selected_ulp:
            filtered = filtered[filtered["unit_code"] == selected_ulp]

        # Per ULP aggregation (for selected period or latest non-zero period)
        ulp_df = filtered
        if not selected_periode and len(work):
            # Use average for saldo, sum for PRR across periods with realization
            non_zero = work[work["realisasi_saldo"] > 0]
            if len(non_zero):
                latest_p = non_zero["periode"].iloc[-1]
                ulp_df = work[work["periode"] == latest_p]

        by_ulp = []
        if len(ulp_df):
            g = ulp_df.groupby(["unit_code", "ulp"], as_index=False).agg(
                target_saldo=("target_saldo", "mean"),
                realisasi_saldo=("realisasi_saldo", "mean"),
                target_prr=("target_prr", "sum"),
                realisasi_prr=("realisasi_prr", "sum"),
                target_transaksi=("target_transaksi", "sum"),
                realisasi_transaksi=("realisasi_transaksi", "sum"),
            ).sort_values("unit_code")
            for _, r in g.iterrows():
                by_ulp.append({
                    "unit_code": r["unit_code"],
                    "ulp": r["ulp"],
                    "target_saldo": round(float(r["target_saldo"]), 2),
                    "realisasi_saldo": round(float(r["realisasi_saldo"]), 2),
                    "target_prr": float(r["target_prr"]),
                    "realisasi_prr": float(r["realisasi_prr"]),
                    "pct_prr": round((float(r["realisasi_prr"]) / float(r["target_prr"]) * 100.0) if r["target_prr"] else 0.0, 2),
                    "target_transaksi": float(r["target_transaksi"]),
                    "realisasi_transaksi": float(r["realisasi_transaksi"]),
                })

        # Monthly trend
        by_periode = []
        p_src = work[work["unit_code"] == selected_ulp] if selected_ulp else work
        for p in periodes:
            sub = p_src[p_src["periode"] == p]
            if len(sub) == 0:
                continue
            by_periode.append({
                "periode": p,
                "target_saldo": round(float(sub["target_saldo"].sum()), 2),
                "realisasi_saldo": round(float(sub["realisasi_saldo"].sum()), 2),
                "target_prr": float(sub["target_prr"].sum()),
                "realisasi_prr": float(sub["realisasi_prr"].sum()),
            })

        kpi = {
            "target_saldo_juta": round(sum(x["target_saldo"] for x in by_ulp), 2),
            "realisasi_saldo_juta": round(sum(x["realisasi_saldo"] for x in by_ulp), 2),
            "target_prr": float(filtered["target_prr"].sum()),
            "realisasi_prr": float(filtered["realisasi_prr"].sum()),
            "realisasi_transaksi": float(filtered["realisasi_transaksi"].sum()),
            "target_transaksi": float(filtered["target_transaksi"].sum()),
        }

        return {
            "meta": {"source_mode": self._source_mode},
            "periodes": periodes,
            "kpi": kpi,
            "by_ulp": by_ulp,
            "by_periode": by_periode,
            "rows": filtered.to_dict(orient="records"),
        }

    def export_detail_csv(self, params):
        payload = self.get_cashin_payload({**params, "page": 1, "page_size": 50000})
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["No", "ULP", "IDPEL", "NAMA", "ALAMAT", "TARIF", "DAYA", "RBM", "KOGOL", "LEMBAR", "RP PTL"])
        for r in payload["detail_pelanggan"]["rows"]:
            writer.writerow([
                r["no"], r["ulp"], r["idpel"], r["nama"], r["alamat"],
                r["tarif"], r["daya"], r["rbm"], r["kogol"], r["lembar"], int(r["rpptl"]),
            ])
        return buf.getvalue()
