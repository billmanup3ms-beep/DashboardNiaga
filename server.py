import argparse
import json
import mimetypes
import os
import queue
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from data_service import DashboardDataService
from pipeline_runner import PipelineRunner

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(PROJECT_DIR, "static")

data_service = DashboardDataService(PROJECT_DIR)
pipeline_runner = PipelineRunner(
    PROJECT_DIR, on_complete_refresh=lambda: data_service.ensure_loaded(force=True)
)


class DashboardHTTPHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        # Keep console clean
        pass

    def _send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    def _serve_static(self, rel_path):
        if rel_path in ("", "/"):
            rel_path = "index.html"
        rel_path = rel_path.lstrip("/")
        safe_path = os.path.normpath(os.path.join(STATIC_DIR, rel_path))
        if not safe_path.startswith(STATIC_DIR) or not os.path.isfile(safe_path):
            self.send_error(404, "File not found")
            return
        ctype, _ = mimetypes.guess_type(safe_path)
        ctype = ctype or "application/octet-stream"
        with open(safe_path, "rb") as f:
            content = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = {k: v[0] for k, v in parse_qs(parsed.query).items()}

        if path == "/api/health":
            self._send_json({"status": "ok"})
            return

        if path == "/api/dashboard/cashin":
            try:
                payload = data_service.get_cashin_payload(qs)
                self._send_json(payload)
            except Exception as e:
                self._send_json({"error": str(e)}, status=500)
            return

        if path == "/api/dashboard/kinerja":
            try:
                payload = data_service.get_kinerja_payload(qs)
                self._send_json(payload)
            except Exception as e:
                self._send_json({"error": str(e)}, status=500)
            return

        if path == "/api/data/export":
            try:
                csv_text = data_service.export_detail_csv(qs)
                body = csv_text.encode("utf-8-sig")
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header(
                    "Content-Disposition",
                    'attachment; filename="detail_tunggakan_up3_maksel.csv"',
                )
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                self._send_json({"error": str(e)}, status=500)
            return

        if path == "/api/pipeline/status":
            self._send_json(pipeline_runner.get_status())
            return

        if path == "/api/pipeline/stream":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()

            q = pipeline_runner.subscribe()
            try:
                # Send initial state snapshot
                init_evt = f"event: state\ndata: {json.dumps(pipeline_runner.get_status())}\n\n"
                self.wfile.write(init_evt.encode("utf-8"))
                self.wfile.flush()

                while True:
                    try:
                        msg = q.get(timeout=15)
                        frame = (
                            f"event: {msg['event']}\n"
                            f"data: {json.dumps(msg['data'], ensure_ascii=False)}\n\n"
                        )
                        self.wfile.write(frame.encode("utf-8"))
                        self.wfile.flush()
                    except queue.Empty:
                        self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                pipeline_runner.unsubscribe(q)
            return

        self._serve_static(path)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/data/refresh":
            try:
                data_service.ensure_loaded(force=True)
                self._send_json({
                    "ok": True,
                    "source_mode": data_service._source_mode,
                    "last_error": data_service._last_error,
                })
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, status=500)
            return

        if path == "/api/pipeline/run":
            body = self._read_json_body()
            mode = body.get("mode", "sequential")
            thbl = body.get("thbl")
            ok, msg = pipeline_runner.start(mode=mode, thbl=thbl)
            self._send_json({"ok": ok, "message": msg, "state": pipeline_runner.get_status()}, status=200 if ok else 409)
            return

        if path == "/api/pipeline/stop":
            ok, msg = pipeline_runner.stop()
            self._send_json({"ok": ok, "message": msg, "state": pipeline_runner.get_status()})
            return

        self._send_json({"error": "Not found"}, status=404)


def main():
    parser = argparse.ArgumentParser(description="Dashboard Piutang UP3 Makassar Selatan")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()

    # Pre-warm cache in background
    data_service.ensure_loaded(force=False)

    server = ThreadingHTTPServer((args.host, args.port), DashboardHTTPHandler)
    print(f"======================================================================")
    print(f"  DASHBOARD PIUTANG UP3 MAKASSAR SELATAN")
    print(f"  URL    : http://{args.host}:{args.port}")
    print(f"  Source : {data_service._source_mode}")
    print(f"======================================================================")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
