"""Local editor for harrisonzukas.com.

Run:  python admin/server.py   (or double-click admin/start.bat)
Opens http://127.0.0.1:8787 in your browser. Only reachable from this computer.
"""
import base64
import html
import json
import os
import subprocess
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ADMIN = ROOT / "admin"
CONTENT = ROOT / "content.json"
TEMPLATE = ADMIN / "template.html"
INDEX = ROOT / "index.html"
IMAGES = ROOT / "images"
PORT = 8787
ALLOWED = {"jpg": "jpg", "jpeg": "jpg", "png": "png", "webp": "webp", "gif": "gif"}


def load_content():
    with open(CONTENT, encoding="utf-8") as f:
        return json.load(f)


def render(content):
    tpl = TEMPLATE.read_text(encoding="utf-8")
    block = ""
    if content.get("headline"):
        block += f"  <h1>{html.escape(content['headline'])}</h1>\n"
    if content.get("text"):
        block += f"  <p>{html.escape(content['text'])}</p>\n"
    size = max(5, min(100, int(content.get("size", 34))))
    return (tpl.replace("{{SIZE}}", str(size))
               .replace("{{PHOTO}}", html.escape(content.get("photo", "images/profile.jpg")))
               .replace("{{TEXT_BLOCK}}", block))


def git(*args):
    p = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    return p.returncode, (p.stdout + p.stderr).strip()


def apply_update(payload):
    content = load_content()
    content["headline"] = payload.get("headline", "").strip()
    content["text"] = payload.get("text", "").strip()
    content["size"] = max(5, min(100, int(payload.get("size", content.get("size", 34)))))

    img = payload.get("image")
    if img and img.get("data"):
        ext = img.get("name", "").rsplit(".", 1)[-1].lower()
        if ext not in ALLOWED:
            raise ValueError("Image must be a JPG, PNG, WEBP, or GIF file.")
        data = base64.b64decode(img["data"].split(",", 1)[-1])
        if len(data) > 15 * 1024 * 1024:
            raise ValueError("Image is larger than 15 MB.")
        IMAGES.mkdir(exist_ok=True)
        new_name = f"profile.{ALLOWED[ext]}"
        for old in IMAGES.glob("profile.*"):
            if old.name != new_name:
                old.unlink()
        (IMAGES / new_name).write_bytes(data)
        content["photo"] = f"images/{new_name}"

    CONTENT.write_text(json.dumps(content, indent=2) + "\n", encoding="utf-8")
    INDEX.write_text(render(content), encoding="utf-8")

    git("add", "-A")
    code, out = git("status", "--porcelain")
    if not out:
        return {"ok": True, "changed": False, "message": "Nothing changed, so there was nothing to publish."}
    code, out = git("commit", "-q", "-m", "Update site content")
    if code != 0:
        raise RuntimeError("Commit failed:\n" + out)
    code, out = git("push", "-q", "origin", "main")
    if code != 0:
        raise RuntimeError("Push failed:\n" + out)
    return {"ok": True, "changed": True,
            "message": "Pushed. harrisonzukas.com will update in about a minute."}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, status, body, ctype="application/json"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body)
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _json_body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/":
            self._send(200, (ADMIN / "index.html").read_bytes(), "text/html; charset=utf-8")
        elif path == "/api/content":
            self._send(200, load_content())
        elif path.startswith("/images/"):
            f = IMAGES / Path(path).name
            if f.is_file():
                self._send(200, f.read_bytes(), "image/" + ("jpeg" if f.suffix == ".jpg" else f.suffix[1:]))
            else:
                self._send(404, {"error": "not found"})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        try:
            payload = self._json_body()
            if self.path == "/api/preview":
                c = load_content()
                c.update({k: payload.get(k, c.get(k)) for k in ("headline", "text", "size")})
                if (payload.get("image") or {}).get("data"):
                    c["photo"] = payload["image"]["data"]
                self._send(200, render(c), "text/html; charset=utf-8")
            elif self.path == "/api/update":
                self._send(200, apply_update(payload))
            else:
                self._send(404, {"error": "not found"})
        except Exception as e:
            self._send(500, {"ok": False, "message": str(e)})


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}/"
    print(f"Editor running at {url}  (Ctrl+C to stop)")
    if "--no-browser" not in sys.argv:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
