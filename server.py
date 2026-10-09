#!/usr/bin/env python3
"""Local dashboard: http://127.0.0.1:8787  (stdlib only, localhost only)."""
import json, os, re, subprocess, sys, threading
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from digest import HANDLE

ROOT = Path(__file__).resolve().parent
DATA, OUT = ROOT / "data", ROOT / "data" / "digests"
LOG, PROGRESS = DATA / "last-run.log", DATA / "progress.json"
PORT = int(os.environ.get("PORT", 8787))
VIDEO_URL = re.compile(r"^https://(www\.)?(instagram\.com/([\w.]+/)?(reel|reels|p)/[\w-]+|youtube\.com/(shorts/|watch\?v=)[\w-]+|youtu\.be/[\w-]+|(www\.)?tiktok\.com/@[\w.]+/video/\d+)[/\w?=&.-]*$")
job = {"proc": None, "started": None}
lock = threading.Lock()
stats_lock = threading.Lock()


def progress():
    p = json.loads(PROGRESS.read_text()) if PROGRESS.exists() else {}
    if "start" not in p:
        p = {"start": date.today().isoformat(), "done": {}}
        PROGRESS.write_text(json.dumps(p))
    p.setdefault("posted", {})  # idea title -> when he ticked it posted (by title, so reruns can't shift it)
    return p


class H(BaseHTTPRequestHandler):
    def send(self, code, body, ctype="application/json", headers=None):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == "/":
            return self.send(200, (ROOT / "dashboard.html").read_text().replace("@your_handle", "@" + HANDLE).encode(), "text/html; charset=utf-8")
        if u.path.startswith("/img/"):
            f = DATA / "img" / u.path[5:]
            if not re.fullmatch(r"[\w.-]+\.jpg", u.path[5:]) or not f.exists():
                return self.send(404, {"error": "no image"})
            return self.send(200, f.read_bytes(), "image/jpeg")
        if u.path.startswith("/carousels/"):
            f = DATA / u.path[1:]
            if not re.fullmatch(r"/carousels/[\d-]+/slide-\d+\.png", u.path) or not f.exists():
                return self.send(404, {"error": "no slide"})
            return self.send(200, f.read_bytes(), "image/png")
        if u.path == "/api/carousels":
            return self.send(200, [json.loads(f.read_text()) for f in (DATA / "carousels").glob("*/meta.json")])
        if u.path.startswith("/guides/"):
            f = DATA / "guides" / u.path[8:]
            if not re.fullmatch(r"[\w.-]+\.pdf", u.path[8:]) or not f.exists():
                return self.send(404, {"error": "no guide"})
            # Save/download from the browser uses the video's name, not the URL slug or page title.
            name = next((m.get("filename") for m in map(lambda j: json.loads(j.read_text()), f.parent.glob("*.json"))
                         if m.get("pdf") == u.path and m.get("filename")), f.name)
            return self.send(200, f.read_bytes(), "application/pdf",
                             {"Content-Disposition": f"inline; filename*=UTF-8''{quote(name)}"})
        if u.path == "/api/usage":
            f = DATA / "usage.jsonl"
            rows = [json.loads(l) for l in f.read_text().splitlines() if l.strip()] if f.exists() else []
            return self.send(200, rows[-50:])
        if u.path == "/api/digests":
            return self.send(200, sorted((f.stem for f in OUT.glob("????-??-??.json")), reverse=True))
        if u.path == "/api/digest":
            d = (q.get("date") or [""])[0]
            f = OUT / f"{d}.json"
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d) or not f.exists():
                return self.send(404, {"error": "no digest for that date"})
            return self.send(200, json.loads(f.read_text()))
        if u.path == "/api/status":
            p = job["proc"]
            log = LOG.read_text().splitlines()[-40:] if LOG.exists() else []
            sched = DATA / "scheduled-run.log"
            sched_log = [l for l in sched.read_text().splitlines() if l.startswith("[")][-12:] if sched.exists() else []
            return self.send(200, {"running": bool(p and p.poll() is None), "started": job["started"],
                                   "exit": None if not p or p.poll() is None else p.returncode, "log": log, "scheduled_log": sched_log})
        if u.path == "/api/progress":
            return self.send(200, progress())
        if u.path == "/api/stats":
            f = DATA / "my-stats.json"
            return self.send(200, json.loads(f.read_text()) if f.exists() else {"reels": [], "history": {}})
        if u.path == "/api/hooks":
            d = parse_qs(u.query).get("date", [""])[0]
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d):
                return self.send(400, {"error": "bad date"})
            return self.send(200, {f.stem.rsplit("-", 1)[1]: json.loads(f.read_text()) for f in (DATA / "hooks").glob(f"{d}-*.json")})
        if u.path == "/api/guides":
            gdir = DATA / "guides"
            out = []
            for m in sorted(gdir.glob("*.json"), key=lambda f: -f.stat().st_mtime) if gdir.exists() else []:
                txt = gdir / f"{m.stem}.md"
                if txt.exists():
                    out.append({**json.loads(m.read_text()), "guide": txt.read_text()})
            return self.send(200, out)
        self.send(404, {"error": "not found"})

    def do_POST(self):
        # Block other websites from driving this local server.
        origin = self.headers.get("Origin")
        if origin and origin not in (f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"):
            return self.send(403, {"error": "bad origin"})
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n) or b"{}") if n < 10_000 else {}
        except ValueError:
            return self.send(400, {"error": "bad json"})
        path = urlparse(self.path).path

        if path == "/api/run":
            with lock:
                if job["proc"] and job["proc"].poll() is None:
                    return self.send(409, {"error": "already running"})
                job["proc"] = subprocess.Popen([str(ROOT / "run-digest.sh")], stdout=LOG.open("w"),
                                               stderr=subprocess.STDOUT, cwd=ROOT)
                job["started"] = datetime.now().isoformat(timespec="seconds")
            return self.send(202, {"started": job["started"]})

        if path == "/api/watch":
            url = str(body.get("url", "")).strip()
            if not VIDEO_URL.match(url):
                return self.send(400, {"error": "Paste an Instagram Reel, YouTube Short/video or TikTok link"})
            p = subprocess.run([sys.executable, str(ROOT / "digest.py"), "watch", url], capture_output=True, text=True,
                               timeout=420, cwd=ROOT)
            try:
                return self.send(200, json.loads(p.stdout.strip().splitlines()[-1]))
            except (ValueError, IndexError):
                return self.send(500, {"error": (p.stderr or p.stdout or "watch failed")[-400:]})

        if path == "/api/carousel/open":  # reveal the slides in Finder; the page opens Instagram
            d, n = str(body.get("date", "")), str(body.get("n", ""))
            f = DATA / "carousels" / f"{d}-{n}" / "meta.json"
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d) or not re.fullmatch(r"\d", n) or not f.exists():
                return self.send(400, {"error": "no carousel"})
            subprocess.run(["open", json.loads(f.read_text())["downloads"]])
            return self.send(200, {"ok": True})

        if path in ("/api/guide", "/api/hooks", "/api/carousel"):
            d, n = str(body.get("date", "")), str(body.get("n", ""))
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d) or not re.fullmatch(r"\d", n) or not (OUT / f"{d}.json").exists():
                return self.send(400, {"error": "bad date or idea number"})
            return self.digest_cmd([path.rsplit("/", 1)[1], d, n])

        if path == "/api/stats":
            # Run now also drives Instagram through the same Chrome; two at once can hang, so refuse fast.
            if job["proc"] and job["proc"].poll() is None:
                return self.send(409, {"error": "Run now is reading Instagram right now. Try again when it finishes."})
            if not stats_lock.acquire(blocking=False):
                return self.send(409, {"error": "Already refreshing stats, give it a few more seconds."})
            try:
                return self.digest_cmd(["stats"], timeout=150)
            finally:
                stats_lock.release()

        if path == "/api/share":
            kw = str(body.get("keyword", ""))
            if not re.fullmatch(r"\w+", kw) or not (DATA / "guides" / f"{kw}.json").exists():
                return self.send(400, {"error": "unknown guide"})
            return self.digest_cmd(["share", kw])

        if path == "/api/posted":
            title = str(body.get("title", "")).strip()
            if not title or len(title) > 300:
                return self.send(400, {"error": "bad title"})
            p = progress()
            if body.get("posted"):
                p["posted"][title] = datetime.now().isoformat(timespec="seconds")
            else:
                p["posted"].pop(title, None)
            PROGRESS.write_text(json.dumps(p))
            return self.send(200, p)

        if path == "/api/progress":
            key = str(body.get("key", ""))
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}#\d", key):
                return self.send(400, {"error": "bad key"})
            p = progress()
            if body.get("done"):
                p["done"][key] = datetime.now().isoformat(timespec="seconds")
            else:
                p["done"].pop(key, None)
            PROGRESS.write_text(json.dumps(p))
            return self.send(200, p)
        self.send(404, {"error": "not found"})

    def digest_cmd(self, args, timeout=420):
        """Run a digest.py subcommand that prints one JSON line; pass it through."""
        try:
            p = subprocess.run([sys.executable, str(ROOT / "digest.py"), *args], capture_output=True, text=True, timeout=timeout, cwd=ROOT)
        except subprocess.TimeoutExpired:
            return self.send(504, {"error": f"Timed out after {timeout}s. Is Chrome open with the OpenCLI extension on?"})
        try:
            return self.send(200, json.loads(p.stdout.strip().splitlines()[-1]))
        except (ValueError, IndexError):
            return self.send(500, {"error": (p.stderr or p.stdout or "failed").strip()[-300:]})

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    DATA.mkdir(exist_ok=True)
    print(f"Dashboard: http://127.0.0.1:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
