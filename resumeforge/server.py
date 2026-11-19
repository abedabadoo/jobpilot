"""Loopback-only desktop UI and small JobPilot-ready JSON API."""
from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import threading
import uuid
import webbrowser
import urllib.request

from .engine import run
from .importing import import_document
from .ideas import IdeaRequest, brainstorm
from .models import ModelSettings, RunRequest
from .planning import model_health
from .local_runtime import default_settings
from . import __version__


STATIC = Path(__file__).with_name("static")


def serve(port=8765, data_dir=None, open_browser=False):
    data_dir = Path(data_dir) if data_dir else Path.cwd() / ".local-runs"
    data_dir.mkdir(parents=True, exist_ok=True)
    runs = {}
    lock = threading.Lock()
    # Serial execution avoids memory spikes and keeps PDF font registration safe.
    executor = ThreadPoolExecutor(max_workers=1)

    def do_run(run_id, request):
        def progress(message):
            with lock:
                runs[run_id]["message"] = message
        try:
            result = run(request, data_dir/run_id, progress)
            result.update(id=run_id, pdf_url=f"/api/runs/{run_id}/preview.pdf")
            if result["status"] == "ready":
                result["download_url"] = f"/api/runs/{run_id}/resume.pdf"
            with lock:
                runs[run_id] = result
        except Exception as exc:
            with lock:
                runs[run_id] = {"id":run_id,"status":"failed","error":str(exc),"message":str(exc)}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            # Requests contain private resume text; never log their bodies.
            pass

        def reply(self, payload, code=200, content_type="application/json"):
            body = json.dumps(payload).encode() if content_type == "application/json" else payload
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length",str(len(body)))
            self.send_header("Cache-Control","no-store")
            self.send_header("X-Content-Type-Options","nosniff")
            self.send_header("Referrer-Policy","no-referrer")
            self.end_headers()
            self.wfile.write(body)

        def allowed(self):
            hosts = {f"localhost:{port}",f"127.0.0.1:{port}"}
            if self.headers.get("Host") not in hosts:
                self.reply({"error":"Invalid local host"},403)
                return False
            origin = self.headers.get("Origin")
            if origin and origin not in {"http://"+h for h in hosts}:
                self.reply({"error":"Requests must originate from the local app"},403)
                return False
            return True

        def do_GET(self):
            if not self.allowed():
                return
            path = self.path.split("?",1)[0]
            if path == "/api/health":
                return self.reply({"status":"ok","app":"ResumeForge","version":__version__})
            if path == "/api/bootstrap":
                return self.reply({"profile":json.loads((Path(__file__).with_name("data")/"abu.profile.json").read_text(encoding="utf-8")),"settings":default_settings().model_dump()})
            match = re.fullmatch(r"/api/runs/([a-f0-9]{32})(/(preview|resume)\.pdf)?",path)
            if match:
                run_id, suffix, kind = match.groups()
                with lock:
                    result = runs.get(run_id)
                if result is None:
                    return self.reply({"error":"Run not found"},404)
                if suffix:
                    if kind == "resume" and result["status"] != "ready":
                        return self.reply({"error":"This draft has not passed export checks"},409)
                    file = data_dir/run_id/(kind+".pdf")
                    if not file.exists():
                        return self.reply({"error":"Preview is not ready"},404)
                    return self.reply(file.read_bytes(),content_type="application/pdf")
                return self.reply(result)
            files = {"/":"index.html","/index.html":"index.html","/app.js":"app.js","/styles.css":"styles.css"}
            if path in files:
                file = STATIC/files[path]
                types = {".html":"text/html; charset=utf-8",".js":"text/javascript; charset=utf-8",".css":"text/css; charset=utf-8"}
                return self.reply(file.read_bytes(),content_type=types[file.suffix])
            self.reply({"error":"Not found"},404)

        def do_POST(self):
            if not self.allowed():
                return
            if self.headers.get("Content-Type","").split(";",1)[0] != "application/json":
                return self.reply({"error":"Expected application/json"},415)
            try:
                length = int(self.headers.get("Content-Length","0"))
                if length < 1 or length > 15*1024*1024:
                    raise ValueError("Request must be between 1 byte and 15 MiB")
                body = json.loads(self.rfile.read(length))
                if self.path == "/api/run":
                    request = RunRequest.model_validate(body)
                    with lock:
                        if sum(x.get("status")=="running" for x in runs.values()) >= 3:
                            return self.reply({"error":"Three runs are queued. Wait for one to finish."},429)
                        run_id = uuid.uuid4().hex
                        runs[run_id] = {"id":run_id,"status":"running","message":"Queued for local processing"}
                    executor.submit(do_run,run_id,request)
                    return self.reply(runs[run_id],202)
                if self.path == "/api/analyze":
                    from .job_analysis import analyze_posting
                    request = RunRequest.model_validate(body)
                    priorities = executor.submit(analyze_posting, request.profile, request.job_description,
                                                 request.keywords, request.settings).result()
                    return self.reply({"priorities": priorities})
                if self.path == "/api/ideas":
                    request = IdeaRequest.model_validate(body)
                    return self.reply(executor.submit(brainstorm, request).result())
                if self.path == "/api/model-health":
                    return self.reply(model_health(ModelSettings.model_validate(body)))
                if self.path == "/api/import":
                    content = base64.b64decode(body["data_base64"],validate=True)
                    return self.reply(import_document(body["filename"],content,ModelSettings.model_validate(body.get("settings",{}))))
                return self.reply({"error":"Not found"},404)
            except Exception as exc:
                return self.reply({"error":str(exc)},400)

    url = f"http://127.0.0.1:{port}"
    try:
        server = ThreadingHTTPServer(("127.0.0.1",port), Handler)
    except OSError as exc:
        executor.shutdown(wait=False,cancel_futures=True)
        try:
            with urllib.request.urlopen(url+"/api/health",timeout=2) as response:
                existing = json.load(response)
            if existing.get("app") == "ResumeForge":
                print(f"ResumeForge is already running at {url}",flush=True)
                if open_browser:
                    webbrowser.open(url)
                return
        except Exception:
            pass
        raise RuntimeError(f"Port {port} is occupied by another service; choose a different --port.") from exc
    print(f"ResumeForge is running at {url}\nData: {data_dir}\nPress Ctrl+C to quit.",flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        executor.shutdown(wait=False,cancel_futures=True)
