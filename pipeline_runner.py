import json
import os
import queue
import subprocess
import sys
import threading
import time
from datetime import datetime


class PipelineRunner:
    """Menjalankan scripts/uat.py dan scripts/update_saldo_db.py secara berurutan dengan live log streaming."""

    def __init__(self, project_dir, on_complete_refresh=None):
        self.project_dir = project_dir
        self.scripts_dir = os.path.join(project_dir, "scripts")
        self.uat_script = os.path.join(self.scripts_dir, "uat.py")
        self.update_script = os.path.join(self.scripts_dir, "update_saldo_db.py")
        self.on_complete_refresh = on_complete_refresh

        self._lock = threading.Lock()
        self._proc = None
        self._stop_requested = False
        self._subscribers = []
        self._logs = []
        self._max_logs = 800

        self.state = {
            "running": False,
            "mode": None,
            "started_at": None,
            "finished_at": None,
            "overall_status": "idle",  # idle | running | success | failed | stopped
            "steps": {
                "uat": {"status": "idle", "exit_code": None, "label": "1. UAT (Ambil Token Bearer)"},
                "update_db": {"status": "idle", "exit_code": None, "label": "2. Update Saldo DB (6 UNITUP → Google Sheets)"},
                "refresh": {"status": "idle", "exit_code": None, "label": "3. Refresh Data Dashboard"},
            },
        }

    def get_token_info(self):
        candidates = [
            os.path.join(self.scripts_dir, "user_token.json"),
            r"D:\BOT\user_token.json",
        ]
        for path in candidates:
            if os.path.isfile(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    tok = str(data.get("user_token", ""))
                    valid = len(tok) > 30 and tok != "INVALID"
                    mtime = datetime.fromtimestamp(os.path.getmtime(path)).strftime("%d/%m/%Y %H:%M:%S")
                    return {
                        "exists": True,
                        "valid": valid,
                        "path": path,
                        "updated_at": data.get("updated_at") or mtime,
                        "preview": f"{tok[:18]}...{tok[-8:]}" if valid else "INVALID",
                    }
                except Exception:
                    pass
        return {
            "exists": False,
            "valid": False,
            "path": os.path.join(self.scripts_dir, "user_token.json"),
            "updated_at": None,
            "preview": None,
        }

    def get_status(self):
        with self._lock:
            return {
                **json.loads(json.dumps(self.state)),
                "token": self.get_token_info(),
                "logs": self._logs[-200:],
            }

    def subscribe(self):
        q = queue.Queue(maxsize=500)
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q):
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def _broadcast(self, event_type, payload):
        msg = {"event": event_type, "data": payload}
        with self._lock:
            dead = []
            for q in self._subscribers:
                try:
                    q.put_nowait(msg)
                except queue.Full:
                    dead.append(q)
            for d in dead:
                self._subscribers.remove(d)

    def _append_log(self, text, level="info"):
        entry = {
            "ts": datetime.now().strftime("%H:%M:%S"),
            "level": level,
            "text": text,
        }
        with self._lock:
            self._logs.append(entry)
            if len(self._logs) > self._max_logs:
                self._logs = self._logs[-self._max_logs:]
        self._broadcast("log", entry)

    def _emit_state(self):
        self._broadcast("state", self.get_status())

    def start(self, mode="sequential", thbl=None):
        with self._lock:
            if self.state["running"]:
                return False, "Pipeline sedang berjalan. Tunggu hingga selesai atau klik Stop."
            self._stop_requested = False
            self._logs = []
            self.state = {
                "running": True,
                "mode": mode,
                "started_at": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
                "finished_at": None,
                "overall_status": "running",
                "steps": {
                    "uat": {
                        "status": "pending" if mode in ("sequential", "uat") else "skipped",
                        "exit_code": None,
                        "label": "1. UAT (Ambil Token Bearer)",
                    },
                    "update_db": {
                        "status": "pending" if mode in ("sequential", "update_db") else "skipped",
                        "exit_code": None,
                        "label": "2. Update Saldo DB (6 UNITUP → Google Sheets)",
                    },
                    "refresh": {
                        "status": "pending",
                        "exit_code": None,
                        "label": "3. Refresh Data Dashboard",
                    },
                },
            }

        self._emit_state()
        t = threading.Thread(target=self._run_worker, args=(mode, thbl), daemon=True)
        t.start()
        return True, "Pipeline dimulai."

    def stop(self):
        with self._lock:
            if not self.state["running"]:
                return False, "Tidak ada proses yang sedang berjalan."
            self._stop_requested = True
            proc = self._proc
        if proc and proc.poll() is None:
            try:
                proc.terminate()
                self._append_log("[SYSTEM] Menghentikan proses atas permintaan user...", "warn")
            except Exception as e:
                self._append_log(f"[SYSTEM] Gagal terminate proses: {e}", "error")
        return True, "Permintaan stop dikirim."

    def _run_script(self, step_key, script_path, extra_env=None):
        with self._lock:
            self.state["steps"][step_key]["status"] = "running"
        self._emit_state()
        self._append_log(f"▶ Menjalankan {os.path.basename(script_path)} ...", "step")

        if not os.path.isfile(script_path):
            self._append_log(f"[ERROR] File script tidak ditemukan: {script_path}", "error")
            with self._lock:
                self.state["steps"][step_key]["status"] = "failed"
                self.state["steps"][step_key]["exit_code"] = -1
            self._emit_state()
            return False

        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["USER_TOKEN_PATH"] = os.path.join(self.scripts_dir, "user_token.json")
        if extra_env:
            env.update(extra_env)

        try:
            proc = subprocess.Popen(
                [sys.executable, "-u", script_path],
                cwd=self.scripts_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=env,
            )
            with self._lock:
                self._proc = proc

            for line in iter(proc.stdout.readline, ""):
                cleaned = line.rstrip("\r\n")
                if cleaned:
                    lvl = "error" if ("[ERROR]" in cleaned or "Traceback" in cleaned or "[FATAL" in cleaned) else (
                        "warn" if "[WARNING]" in cleaned else (
                            "success" if ("SUKSES" in cleaned or "BERHASIL" in cleaned or "READY" in cleaned) else "info"
                        )
                    )
                    self._append_log(cleaned, lvl)

            proc.wait()
            rc = proc.returncode
        except Exception as e:
            self._append_log(f"[ERROR] Gagal menjalankan script: {e}", "error")
            rc = -1
        finally:
            with self._lock:
                self._proc = None

        with self._lock:
            stopped = self._stop_requested
            self.state["steps"][step_key]["exit_code"] = rc
            if stopped:
                self.state["steps"][step_key]["status"] = "stopped"
            elif rc == 0:
                self.state["steps"][step_key]["status"] = "success"
            else:
                self.state["steps"][step_key]["status"] = "failed"
        self._emit_state()

        if stopped:
            self._append_log(f"■ {os.path.basename(script_path)} dihentikan.", "warn")
            return False
        if rc == 0:
            self._append_log(f"✓ {os.path.basename(script_path)} selesai sukses (exit code 0).", "success")
            return True
        self._append_log(f"✗ {os.path.basename(script_path)} gagal dengan exit code {rc}.", "error")
        return False

    def _run_worker(self, mode, thbl):
        extra_env = {}
        if thbl:
            extra_env["THBL"] = str(thbl)

        ok = True
        try:
            if mode in ("sequential", "uat"):
                ok = self._run_script("uat", self.uat_script, extra_env)
                if not ok and mode == "sequential":
                    self._append_log(
                        "[PIPELINE] Step 1 (UAT) gagal/dihentikan — Step 2 (Update Saldo DB) dibatalkan.",
                        "error",
                    )
                    with self._lock:
                        self.state["steps"]["update_db"]["status"] = "skipped"
                        self.state["steps"]["refresh"]["status"] = "skipped"

            if ok and mode in ("sequential", "update_db") and not self._stop_requested:
                ok = self._run_script("update_db", self.update_script, extra_env)

            if ok and not self._stop_requested:
                with self._lock:
                    self.state["steps"]["refresh"]["status"] = "running"
                self._emit_state()
                self._append_log("▶ Menyegarkan cache data dashboard dari Google Sheets...", "step")
                try:
                    if self.on_complete_refresh:
                        self.on_complete_refresh()
                    with self._lock:
                        self.state["steps"]["refresh"]["status"] = "success"
                        self.state["steps"]["refresh"]["exit_code"] = 0
                    self._append_log("✓ Data dashboard berhasil disegarkan!", "success")
                except Exception as e:
                    with self._lock:
                        self.state["steps"]["refresh"]["status"] = "failed"
                        self.state["steps"]["refresh"]["exit_code"] = 1
                    self._append_log(f"[WARNING] Refresh cache gagal: {e}", "warn")
        finally:
            with self._lock:
                self.state["running"] = False
                self.state["finished_at"] = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
                if self._stop_requested:
                    self.state["overall_status"] = "stopped"
                elif ok:
                    self.state["overall_status"] = "success"
                else:
                    self.state["overall_status"] = "failed"
            self._emit_state()
            self._broadcast("done", {"status": self.state["overall_status"]})
