#!/usr/bin/env python3
# SNAG - grab videos from YouTube / TikTok / X and 1000+ more sites.
# Copyright (C) 2026 TNJAPS
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. It is distributed WITHOUT ANY WARRANTY; see the GNU General Public
# License for more details. You should have received a copy of the licence along
# with this program. If not, see <https://www.gnu.org/licenses/>.
#
# Additional permission under GNU GPL version 3 section 7: if you modify this
# Program, or any covered work, by linking or combining it with the Google Mobile
# Ads SDK, the Google User Messaging Platform SDK, or Google Play services (or
# modified versions of those libraries), containing parts covered by terms other
# than the GNU General Public License, the copyright holder grants you additional
# permission to convey the resulting work. See docs/LICENSE-EXCEPTION.md.

"""
SNAG — grab videos from YouTube / TikTok / X(Twitter) and 1000+ more sites.

Requires: Python 3.8+,  pip install yt-dlp   (FFmpeg optional, needed for MP3 + HD merging)

Run the web app :  python snag.py            → opens http://localhost:8765
Grab from CLI   :  python snag.py "https://www.tiktok.com/@u/video/123" -q 720
                  python snag.py "<url>" -q mp3 -o ~/Music
                  python snag.py "<url>" --cookies-from-browser chrome
"""
import argparse, json, os, re, secrets, shutil, subprocess, sys, threading, uuid, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

try:
    import yt_dlp
    from yt_dlp.utils import DownloadError
except ImportError:
    print("Missing dependency. Install it with:  pip install yt-dlp")
    sys.exit(1)

OUTDIR = Path.cwd() / "snag_downloads"
LOCK = threading.Lock()
JOBS = {}
UPDATE = {"status": "idle", "log": ""}

# True when running inside the Android APK (Chaquopy) rather than on a desktop.
ANDROID = (hasattr(sys, "getandroidapilevel")
           or "ANDROID_ROOT" in os.environ
           or "ANDROID_DATA" in os.environ)

# Directory holding the bundled ffmpeg/ffprobe; set by serve() on Android.
FFMPEG_DIR = None

# Base URL once the server is up, so a second serve() call is a no-op. Guarded by
# its own lock: the activity can be created twice in quick succession and both
# startup threads would otherwise race past the check and bind two sockets.
SERVER_URL = None
SERVE_LOCK = threading.Lock()

def outdir_label():
    """Short label for the save folder. os.path.relpath can raise (or return a
    useless ../../.. chain) once OUTDIR sits on Android external storage."""
    if ANDROID:
        return OUTDIR.name
    try:
        return os.path.relpath(OUTDIR)
    except ValueError:
        return str(OUTDIR)

# Shared secret guarding the local HTTP API. Stays None on the desktop, where the
# server is reached from a normal browser; serve() sets one on Android, because
# every other app on the phone can also reach 127.0.0.1 and would otherwise be
# able to list downloads, read them, or queue arbitrary URLs.
TOKEN = None

def _quality(n):
    """Format selector capped at n pixels on the SHORT side.

    Filtering on height alone silently excludes every vertical video: a phone
    clip is 720x1280, so height<=720 matches nothing and the download dies with
    "Requested format is not available". Checking width as well covers portrait,
    and the bare /b tail guarantees we always fall back to something."""
    return (f"bv*[height<={n}]+ba/bv*[width<={n}]+ba/"
            f"b[height<={n}]/b[width<={n}]/b")

QUALITIES = {
    "auto": "bv*+ba/b",
    "1080": _quality(1080),
    "720":  _quality(720),
    "480":  _quality(480),
}
MIME = {".mp4":"video/mp4",".webm":"video/webm",".mkv":"video/x-matroska",".mov":"video/quicktime",".mp3":"audio/mpeg"}

def detect_platform(url):
    u = url.lower()
    if "youtu" in u:            return "youtube", "YT"
    if "tiktok.com" in u:       return "tiktok",  "TT"
    if "twitter.com" in u or re.search(r"x\.com/", u): return "x", "X"
    return "other", ""

def friendly(err, plat=None):
    s = str(err).strip().replace("\n", " ")[:420]
    if "ffmpeg" in s.lower() and not shutil.which("ffmpeg") and not FFMPEG_DIR:
        s += " — MP3 extraction & HD merging need FFmpeg (winget install ffmpeg / brew install ffmpeg / apt install ffmpeg)."
    if plat == "tiktok":
        s += " · TikTok fix: update yt-dlp, then choose cookies from a browser where you are logged in."
    elif plat == "x":
        s += " · X/Twitter may require cookies from a browser where you are logged in."
    return s

def cookie_params(browser=None, cookiefile=None):
    if cookiefile:
        path = Path(cookiefile).expanduser()
        if not path.is_file():
            raise FileNotFoundError(f"Cookies file not found: {path}")
        return {"cookiefile": str(path.resolve())}
    if browser:
        return {"cookiesfrombrowser": (browser,)}
    return {}

BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
              " (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

def base_opts():
    """Extra yt-dlp options needed inside the APK.

    TikTok's edge answers yt-dlp's default headers with a 537-byte "Site
    Maintenance" stub when the request comes from the phone (same public IP as
    the desktop, so it is not geo-blocking); a real browser User-Agent gets the
    genuine page. ffmpeg_location points at the copy bundled in the APK.
    """
    opts = {}
    if ANDROID:
        opts["http_headers"] = {"User-Agent": BROWSER_UA}
    if FFMPEG_DIR:
        opts["ffmpeg_location"] = FFMPEG_DIR
    return opts

def resolve(url, cparams=None):
    """Return a single-video URL + its info dict."""
    opts = {"quiet": True, "no_warnings": True}
    opts.update(base_opts())
    opts.update(cparams or {})
    meta = yt_dlp.YoutubeDL(opts).extract_info(url, download=False)
    if meta.get("_type") == "playlist":
        entries = [e for e in (meta.get("entries") or []) if e]
        if not entries:
            raise RuntimeError("that link is an empty playlist — paste a single video instead")
        return entries[0].get("webpage_url") or url, entries[0], True
    return url, meta, False

def make_hook(job):
    def hook(d):
        with LOCK:
            if d.get("status") == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                job["pct"]   = round(100 * d.get("downloaded_bytes", 0) / total) if total else 0
                job["speed"] = d.get("_speed_str") or ""
                job["eta"]   = d.get("_eta_str") or ""
                job["status"] = "downloading"
            elif d.get("status") == "finished":
                job["status"], job["pct"], job["speed"], job["eta"] = "processing", 100, "", ""
    return hook

def run_job(jid, url, quality, browser=None, cookiefile=None):
    with LOCK:
        JOBS[jid].update(status="probing")
    try:
        plat, prefix = detect_platform(url)
        cparams = cookie_params(browser, cookiefile)
        target, info, was_playlist = resolve(url, cparams)
        # QUALITIES has no "mp3" key, so the branch must come first: the old
        # one-liner evaluated QUALITIES[quality] eagerly and raised KeyError.
        if quality == "mp3":
            fmt = "bestaudio/b"
            pp = [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3",
                   "preferredquality": "192"}]
        else:
            fmt, pp = QUALITIES[quality], []

        before = set(os.listdir(OUTDIR)) if OUTDIR.exists() else set()
        opts = {
            "format": fmt, "postprocessors": pp,
            "outtmpl": str(OUTDIR) + os.sep + (prefix + " " if prefix else "") + "%(title).80s [%(id)s].%(ext)s",
            "merge_output_format": "mp4", "noplaylist": True,
            "quiet": True, "no_warnings": True, "retries": 3,
            "progress_hooks": [make_hook(JOBS[jid])],
        }
        opts.update(base_opts())
        opts.update(cparams)
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([target])

        after = set(os.listdir(OUTDIR))
        new = [f for f in (after - before) if not f.endswith((".part", ".ytdl")) and not f.startswith(".")]
        with LOCK:
            if new:
                p = max((OUTDIR / f for f in new), key=lambda x: x.stat().st_mtime)
                JOBS[jid]["file"], JOBS[jid]["size"] = p.name, p.stat().st_size
            JOBS[jid].update(status="done", pct=100, speed="", eta="")
    except DownloadError as e:
        with LOCK: JOBS[jid].update(status="error", error=friendly(e, plat))
    except Exception as e:
        with LOCK: JOBS[jid].update(status="error", error=f"{type(e).__name__}: {e}"[:300])

def start_job(url, quality, browser=None, cookiefile=None):
    jid = uuid.uuid4().hex[:8]
    with LOCK:
        if len(JOBS) > 30: del JOBS[next(iter(JOBS))]
        JOBS[jid] = {"status": "probing", "pct": 0, "speed": "", "eta": "", "file": "", "error": ""}
    threading.Thread(target=run_job, args=(jid, url, quality, browser, cookiefile), daemon=True).start()
    return jid

def probe(url, browser=None, cookiefile=None):
    target, info, was_playlist = resolve(url, cookie_params(browser, cookiefile))
    plat, _ = detect_platform(url)
    return {"platform": plat, "title": info.get("title", "?"),
            "uploader": info.get("uploader") or info.get("channel") or "",
            "duration": info.get("duration"), "thumbnail": info.get("thumbnail"),
            "playlist": was_playlist}

def list_files():
    items = []
    for p in OUTDIR.iterdir() if OUTDIR.exists() else []:
        if p.is_file() and not p.name.startswith("."):
            tok, _, _ = p.name.partition(" ")
            items.append({"name": p.name, "size": p.stat().st_size, "mtime": p.stat().st_mtime,
                          "platform": {"YT": "youtube", "TT": "tiktok", "X": "x"}.get(tok)})
    return sorted(items, key=lambda x: -x["mtime"])[:15]

def do_update():
    if ANDROID:
        UPDATE.update(status="error",
                      log="yt-dlp is baked into the APK and cannot update itself. "
                          "Rebuild the app to pick up a newer yt-dlp.")
        return
    def update():
        UPDATE.update(status="running", log=f"Updating yt-dlp via {sys.executable} -m pip…")
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp"],
                capture_output=True, text=True, timeout=300,
            )
            UPDATE["log"] = ((result.stdout or "") + "\n" + (result.stderr or ""))[-1000:].strip()
            UPDATE["status"] = "done" if result.returncode == 0 else "error"
        except Exception as exc:
            UPDATE.update(status="error", log=str(exc))
    threading.Thread(target=update, daemon=True).start()

def page_html():
    """PAGE with the per-device config substituted in.

    The phone has no browser profile to read cookies from and cannot update a
    yt-dlp that is baked into the APK, so the page hides both controls and words
    the copy for the device it is actually running on.
    """
    return PAGE.replace("__SNAG_CONFIG__",
                        json.dumps({"android": ANDROID, "token": TOKEN or ""}))

# ---------------------------------------------------------------- web UI
class Handler(BaseHTTPRequestHandler):
    server_version = "Snag/1.0"
    def log_message(self, *a): pass

    def _send(self, body, ctype, code=200):
        self.send_response(code)
        self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)

    def _authed(self, query=""):
        """True when the request may proceed. Always true when TOKEN is unset."""
        if not TOKEN:
            return True
        sent = self.headers.get("X-Snag-Token") or ""
        if not sent:
            from urllib.parse import parse_qs
            sent = (parse_qs(query).get("t") or [""])[0]
        return secrets.compare_digest(sent, TOKEN)

    def _json(self, obj, code=200):
        self._send(json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8", code)

    def do_GET(self):
        p, _, query = self.path.partition("?")
        try:
            if not self._authed(query):
                return self._json({"ok": False, "error": "forbidden"}, 403)
            if p in ("/", "/index.html"): return self._send(page_html().encode(), "text/html; charset=utf-8")
            if p == "/api/files":         return self._json({"outdir": outdir_label(), "files": list_files()})
            if p == "/api/update":        return self._json(UPDATE)
            if p.startswith("/file/"):    return self.serve_file(p[6:])
            m = re.match(r"^/api/job/(\w+)$", p)
            if m:
                with LOCK: j = JOBS.get(m.group(1))
                return self._json(j or {"status": "error", "error": "unknown job"})
            self._json({"ok": False, "error": "not found"}, 404)
        except (BrokenPipeError, ConnectionResetError): pass
        except Exception as e: self._json({"ok": False, "error": friendly(e)}, 500)

    def do_POST(self):
        # Split the query off before matching: the page appends ?t=<token> to every
        # request, so comparing the raw path sent all POSTs to the 404 branch.
        p, _, query = self.path.partition("?")
        try:
            if not self._authed(query):
                return self._json({"ok": False, "error": "forbidden"}, 403)
            n = int(self.headers.get("Content-Length") or 0)
            d = json.loads(self.rfile.read(n) or b"{}")
            browser = d.get("browser") or None
            cookiefile = d.get("cookie_file") or None
            if p == "/api/probe":
                url = (d.get("url") or "").strip()
                if not url: return self._json({"ok": False, "error": "paste a link first"})
                try:    r = {"ok": True, **probe(url, browser, cookiefile)}
                except DownloadError as e: r = {"ok": False, "error": friendly(e, detect_platform(url)[0])}
                except Exception as e: r = {"ok": False, "error": friendly(e, detect_platform(url)[0])}
                return self._json(r)
            if p == "/api/download":
                url = (d.get("url") or "").strip()
                q   = d.get("quality") if d.get("quality") in list(QUALITIES) + ["mp3"] else "auto"
                if not url: return self._json({"ok": False, "error": "paste a link first"}, 400)
                return self._json({"ok": True, "job_id": start_job(url, q, browser, cookiefile)})
            if p == "/api/update":
                if UPDATE["status"] == "running":
                    return self._json({"ok": False, "error": "update already running"}, 409)
                do_update()
                return self._json({"ok": True})
            self._json({"ok": False, "error": "not found"}, 404)
        except (BrokenPipeError, ConnectionResetError): pass
        except Exception as e: self._json({"ok": False, "error": friendly(e)}, 500)

    def serve_file(self, raw):
        from urllib.parse import unquote
        name = os.path.basename(unquote(raw))
        fpath = OUTDIR / name
        if not fpath.is_file(): return self._json({"ok": False, "error": "file not found"}, 404)
        size = fpath.stat().st_size
        start, end, ranged = 0, size - 1, False
        m = re.match(r"bytes=(\d*)-(\d*)", self.headers.get("Range") or "")
        if m:
            ranged = True; start = int(m.group(1) or 0)
            end = min(int(m.group(2)), size - 1) if m.group(2) else size - 1
        ctype = MIME.get(fpath.suffix.lower(), "application/octet-stream")
        self.send_response(206 if ranged else 200)
        self.send_header("Content-Type", ctype); self.send_header("Accept-Ranges", "bytes")
        if ranged: self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(end - start + 1)); self.end_headers()
        with open(fpath, "rb") as f:
            f.seek(start); rem = end - start + 1
            while rem > 0:
                c = f.read(min(1 << 20, rem))
                if not c: break
                self.wfile.write(c); rem -= len(c)

PAGE = r"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>SNAG</title>
<style>
/* SNAG - one job: turn a pasted link into a file on this device.
   Colour is reserved for two things only: the action, and where a file came from. */
:root{
 color-scheme:light dark;

 --bg:#f2f2f7;
 --card:#ffffff;
 --card-2:#f7f7fa;
 --text:#1d1d1f;          /* 15.1:1 on --bg */
 --secondary:#55555b;     /*  6.6:1 on --bg */
 --tertiary:#62626a;      /*  5.4:1 on --bg */
 --sep:rgba(60,60,67,.2);
 /* two accent roles, because one value cannot do both jobs: --accent is INK on a
    surface, --accent-fill is a BACKGROUND under white text. In dark mode a blue
    light enough to read on black (#52a8ff) leaves white at 2.5:1 when used as a
    fill, so the fill stays darker. */
 --accent:#0066cc;        /*  5.6:1 on --card */
 --accent-fill:#0066cc;   /*  white on it: 5.6:1 */
 --accent-fill-press:#0053a8;
 --accent-soft:rgba(0,102,204,.1);
 --success:#1a7f37;       /*  4.6:1 on --success-soft */
 --success-soft:#e9f7ed;
 --danger:#c00015;        /*  5.7:1 on --danger-soft */
 --danger-soft:#fdeced;
 --field:rgba(120,120,128,.14);

 /* the only chromatic vocabulary in the app: where a file came from */
 --yt:#e0102b; --tt:#0aa6a0; --xx:#1d80d8; --other:#8e8e93;

 --r-lg:18px; --r-md:13px; --r-sm:10px;
 --tap:44px;                        /* every control clears this */
 --ease:200ms cubic-bezier(.2,.8,.2,1);
}
@media (prefers-color-scheme:dark){
 :root{
  --bg:#000000;
  --card:#1c1c1e;
  --card-2:#232325;
  --text:#f5f5f7;         /* 15.6:1 on --card */
  --secondary:#a8a8b0;    /*  7.2:1 on --card */
  --tertiary:#949499;     /*  5.6:1 on --card */
  --sep:rgba(235,235,245,.2);
  --accent:#52a8ff;       /*  6.8:1 on --card, ink only */
  --accent-fill:#0b74e0;  /*  white on it: 4.6:1 */
  --accent-fill-press:#0a68cc;
  --accent-soft:rgba(82,168,255,.16);
  --success:#46d05f; --success-soft:#10261a;
  --danger:#ff6b63;  --danger-soft:#2e1416;
  --field:rgba(120,120,128,.24);
  --yt:#ff4a5e; --tt:#2ad4cd; --xx:#5aaef5;
 }
}
@media (prefers-contrast:more){
 :root{--sep:rgba(60,60,67,.55);--secondary:#3a3a40;--tertiary:#44444a}
 @media (prefers-color-scheme:dark){
  :root{--sep:rgba(235,235,245,.5);--secondary:#d0d0d6;--tertiary:#c0c0c6}
 }
}

*{box-sizing:border-box;margin:0}
html{background:var(--bg)}
body{
 background:var(--bg);color:var(--text);min-height:100vh;
 font:400 15px/1.45 -apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI Variable","Segoe UI",Roboto,sans-serif;
 -webkit-font-smoothing:antialiased;
 padding:env(safe-area-inset-top) env(safe-area-inset-right) env(safe-area-inset-bottom) env(safe-area-inset-left);
}
button,input,select{font:inherit;color:inherit}
button{touch-action:manipulation;cursor:pointer}
.hidden{display:none!important}
:focus-visible{outline:3px solid var(--accent);outline-offset:2px;border-radius:4px}

/* ---------- header ---------- */
header{
 position:sticky;top:0;z-index:5;display:flex;align-items:center;gap:12px;
 max-width:720px;margin:0 auto;padding:14px 20px;
 background:color-mix(in srgb,var(--bg) 88%,transparent);
 backdrop-filter:saturate(1.6) blur(18px);-webkit-backdrop-filter:saturate(1.6) blur(18px);
 border-bottom:1px solid transparent;
}
header.stuck{border-bottom-color:var(--sep)}
.mark{
 width:30px;height:30px;flex:0 0 auto;display:grid;place-items:center;border-radius:8px;
 background:var(--accent);color:#fff;
}
.mark svg{width:18px;height:18px;stroke-width:2.2;stroke-linecap:round;stroke-linejoin:round}
.wordmark{font:700 17px/1 -apple-system,BlinkMacSystemFont,"Segoe UI Variable","Segoe UI",Roboto,sans-serif;letter-spacing:-.01em}
#saveMeta{margin-left:auto;color:var(--secondary);font-size:13px;white-space:nowrap}

main{max-width:720px;margin:0 auto;padding:8px 20px 40px}

/* ---------- the link field ---------- */
.field-label{
 display:block;margin:10px 0 8px;color:var(--secondary);
 font:600 13px/1 -apple-system,BlinkMacSystemFont,"Segoe UI Variable","Segoe UI",Roboto,sans-serif;
}
.url-wrap{position:relative;display:flex;align-items:center}
.url-icon{
 position:absolute;left:14px;width:20px;height:20px;pointer-events:none;
 color:var(--tertiary);transition:color var(--ease);
}
/* the field icon IS the platform indicator - no separate badge row needed */
.url-wrap[data-plat=youtube] .url-icon{color:var(--yt)}
.url-wrap[data-plat=tiktok]  .url-icon{color:var(--tt)}
.url-wrap[data-plat=x]       .url-icon{color:var(--xx)}
.url-wrap[data-plat=other]   .url-icon{color:var(--text)}
#url{
 width:100%;height:52px;padding:0 14px 0 44px;border:1px solid var(--sep);border-radius:var(--r-md);
 background:var(--card);outline:none;font-size:16px; /* 16px stops iOS/Android zoom-on-focus */
 transition:border-color var(--ease),box-shadow var(--ease);
}
#url::placeholder{color:var(--tertiary)}
#url:focus{border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-soft)}
#url[aria-invalid=true]{border-color:var(--danger)}
#goBtn{
 width:100%;min-height:50px;margin-top:10px;border:0;border-radius:var(--r-md);
 background:var(--accent-fill);color:#fff;
 font:600 17px/1 -apple-system,BlinkMacSystemFont,"Segoe UI Variable","Segoe UI",Roboto,sans-serif;
 display:flex;align-items:center;justify-content:center;gap:8px;transition:background var(--ease),transform var(--ease);
}
#goBtn:active{background:var(--accent-fill-press);transform:scale(.99)}
#goBtn[disabled]{opacity:.5;pointer-events:none}
.hint{margin-top:9px;color:var(--tertiary);font-size:13px}

/* ---------- options ---------- */
.options{margin-top:18px;border-top:1px solid var(--sep);padding-top:6px}
.options summary{
 display:flex;align-items:center;min-height:var(--tap);color:var(--secondary);
 font-size:14px;list-style:none;
}
.options summary::-webkit-details-marker{display:none}
.options summary::after{content:"";margin-left:auto;width:8px;height:8px;border-right:2px solid var(--tertiary);border-bottom:2px solid var(--tertiary);transform:rotate(45deg);transition:transform var(--ease)}
.options[open] summary::after{transform:rotate(-135deg)}
.tools{display:grid;gap:12px;padding:4px 0 12px}
.tool-field{display:block}
.tool-field .lbl{display:block;margin-bottom:6px;color:var(--secondary);font-size:13px}
.sel,.cf{
 width:100%;height:var(--tap);padding:0 12px;border:1px solid var(--sep);border-radius:var(--r-sm);
 background:var(--card);outline:none;font-size:15px;
}
.sel:focus,.cf:focus{border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-soft)}
.upbtn{
 min-height:var(--tap);padding:0 16px;border:1px solid var(--sep);border-radius:var(--r-sm);
 background:var(--card);font-size:15px;
}
.upbtn:active{background:var(--field)}
.upbtn.busy{opacity:.6;pointer-events:none}
#upStatus{display:block;margin-top:8px;color:var(--secondary);font-size:13px}
.support{max-width:720px;margin:30px auto 0;padding:16px 20px 0;border-top:1px solid var(--sep);color:var(--tertiary);font-size:13px;line-height:1.5;text-align:center}
.support a{color:var(--accent);text-decoration:none;font-weight:600}
.support a:hover{text-decoration:underline}

.errbox{
 margin-top:14px;padding:12px 14px;border-radius:var(--r-md);
 background:var(--danger-soft);color:var(--danger);font-size:14px;overflow-wrap:anywhere;
}

/* ---------- the video card: one object through every state ---------- */
.card{
 position:relative;overflow:hidden;margin-top:20px;border:1px solid var(--sep);
 border-radius:var(--r-lg);background:var(--card);
}
/* the signature: a rail in the colour of wherever the file came from */
.card::before,.grab::before{
 content:"";position:absolute;left:0;top:0;bottom:0;width:4px;background:var(--other);
}
.card.youtube::before,.grab.youtube::before{background:var(--yt)}
.card.tiktok::before, .grab.tiktok::before {background:var(--tt)}
.card.x::before,      .grab.x::before      {background:var(--xx)}

.card-body{display:flex;gap:14px;padding:14px 14px 14px 18px}
.card-body img{width:104px;aspect-ratio:16/9;object-fit:cover;border-radius:var(--r-sm);flex:0 0 auto;background:var(--field)}
.card-info{min-width:0;flex:1}
.src{
 display:block;color:var(--secondary);
 font:600 12px/1 -apple-system,BlinkMacSystemFont,"Segoe UI Variable","Segoe UI",Roboto,sans-serif;
}
.card h2{
 margin:5px 0 4px;font:600 16px/1.3 -apple-system,BlinkMacSystemFont,"Segoe UI Variable","Segoe UI",Roboto,sans-serif;
 display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;
}
.meta{color:var(--secondary);font-size:13px}

.chips{display:flex;flex-wrap:wrap;gap:8px;padding:0 14px 14px 18px}
.chip{
 min-height:var(--tap);padding:0 15px;border:1px solid var(--sep);border-radius:var(--r-sm);
 background:var(--card);font:600 15px/1 -apple-system,BlinkMacSystemFont,"Segoe UI Variable","Segoe UI",Roboto,sans-serif;
 transition:background var(--ease),border-color var(--ease),color var(--ease);
}
.chip:active{background:var(--field)}
.chip.picked{background:var(--accent-fill);border-color:var(--accent-fill);color:#fff}
.chips.busy .chip{opacity:.4}
.chips.busy .chip.picked{opacity:1}

/* progress lives inside the card, not in a separate bar */
.job{display:flex;align-items:center;gap:12px;padding:13px 14px 13px 18px;border-top:1px solid var(--sep);background:var(--card-2)}
.job.done{background:var(--success-soft);border-top-color:transparent}
.job.fail{background:var(--danger-soft);border-top-color:transparent}
.pct{
 min-width:46px;font:600 15px/1 -apple-system,BlinkMacSystemFont,"Segoe UI Variable","Segoe UI",Roboto,sans-serif;
 font-variant-numeric:tabular-nums;
}
.job.done .pct{color:var(--success)}
.job.fail .pct{color:var(--danger)}
.bar{flex:1;height:6px;border-radius:999px;background:var(--field);overflow:hidden}
.bar i{display:block;height:100%;border-radius:inherit;background:var(--accent);transition:width 400ms ease}
.bar.ind i{width:40%!important;animation:sweep 1.1s ease-in-out infinite}
@keyframes sweep{0%{transform:translateX(-110%)}100%{transform:translateX(260%)}}
.jobtext{color:var(--secondary);font-size:13px;white-space:nowrap}
.job .dtext{color:var(--success);font-size:14px;overflow-wrap:anywhere;white-space:normal}
.job.fail .dtext{color:var(--danger)}

/* ---------- downloads ---------- */
.recent{margin-top:30px}
.recent-head{display:flex;align-items:baseline;gap:10px;margin-bottom:10px}
.recent h2{font:700 20px/1.2 -apple-system,BlinkMacSystemFont,"Segoe UI Variable","Segoe UI",Roboto,sans-serif;letter-spacing:-.015em}
.recent-head .count{color:var(--tertiary);font-size:14px}
#recentList{list-style:none;padding:0;display:grid;gap:8px}
.grab{
 position:relative;overflow:hidden;display:flex;align-items:center;gap:10px;
 min-height:64px;padding:10px 10px 10px 18px;border:1px solid var(--sep);
 border-radius:var(--r-md);background:var(--card);
}
.grab.fresh{box-shadow:0 0 0 3px var(--accent-soft)}
.grow{min-width:0;flex:1}
.grab b{display:block;font:600 15px/1.3 -apple-system,BlinkMacSystemFont,"Segoe UI Variable","Segoe UI",Roboto,sans-serif;
 display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.sub{display:block;margin-top:2px;color:var(--secondary);font-size:13px}
.rowbtn{
 width:var(--tap);height:var(--tap);flex:0 0 auto;display:grid;place-items:center;
 border:1px solid var(--sep);border-radius:50%;background:var(--card);color:var(--text);
}
.rowbtn:active{background:var(--field)}
.rowbtn svg{width:18px;height:18px;stroke-width:2;stroke-linecap:round;stroke-linejoin:round;fill:none;stroke:currentColor}
.grab video{width:100%;flex-basis:100%;margin-top:10px;border-radius:var(--r-sm);max-height:60vh;background:#000}
#emptyRecent{padding:22px;border:1px dashed var(--sep);border-radius:var(--r-md);text-align:center;color:var(--tertiary);font-size:14px}

@media (min-width:600px){
 .chips{padding-bottom:16px}
 #goBtn{width:auto;min-width:180px;margin-left:auto}
 .url-row{display:grid;grid-template-columns:1fr auto;gap:10px;align-items:start}
 #goBtn{margin-top:0;height:52px}
 .tools{grid-template-columns:1fr 1fr;align-items:end}
}
@media (prefers-reduced-motion:reduce){
 *,*::before,*::after{animation-duration:.01ms!important;animation-iteration-count:1!important;transition-duration:.01ms!important}
}
</style></head>

<body>
<header id="appbar">
 <span class="mark" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M12 3v11m0 0 4-4m-4 4-4-4"/><path d="M5 15v3a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-3"/></svg></span>
 <span class="wordmark">SNAG</span>
 <span id="saveMeta" aria-live="polite"></span>
</header>

<main>
 <form id="grabForm" novalidate>
  <label class="field-label" for="url">Video link</label>
  <div class="url-row">
   <div class="url-wrap" id="urlWrap">
    <svg class="url-icon" aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M10.6 13.4a4.5 4.5 0 0 0 6.4.1l2-2a4.5 4.5 0 0 0-6.4-6.4l-1.1 1.1"/><path d="M13.4 10.6a4.5 4.5 0 0 0-6.4-.1l-2 2a4.5 4.5 0 0 0 6.4 6.4l1.1-1.1"/></svg>
    <input id="url" type="url" inputmode="url" placeholder="Paste a YouTube, TikTok or X link"
           autocomplete="off" autocapitalize="off" spellcheck="false" aria-describedby="urlHint">
   </div>
   <button type="submit" id="goBtn"><span>Get video</span></button>
  </div>
  <p id="urlHint" class="hint"></p>
 </form>

 <div id="errMsg" class="errbox hidden" role="alert"></div>

 <section id="result" class="hidden" aria-live="polite"></section>

 <details class="options">
  <summary>Options</summary>
  <div class="tools" id="toolsBox"></div>
 </details>

 <section class="recent" aria-labelledby="recentTitle">
  <div class="recent-head">
   <h2 id="recentTitle">Downloads</h2><span class="count" id="recentCount"></span>
  </div>
  <ul id="recentList"></ul>
  <p id="emptyRecent">Nothing yet. Paste a link above.</p>
 </section>

 <footer class="support">SNAG is free and always will be.
  <a id="supportLink" target="_blank" rel="noopener noreferrer">Support it</a>
  if it saved you some time.</footer>
</main>

<script>
const CFG = __SNAG_CONFIG__;
const SUPPORT_URL = "https://github.com/sponsors/tnjappsss";
/* On the phone the server demands a token, because every other app can reach
   127.0.0.1 too. It is empty on the desktop and everything below is a no-op. */
const TOK=CFG.token||"";
const withTok=u=>TOK?u+(u.includes("?")?"&":"?")+"t="+encodeURIComponent(TOK):u;
const api=(u,o)=>{o=o||{};return fetch(withTok(u),{...o,headers:{...(o.headers||{}),...(TOK?{"X-Snag-Token":TOK}:{})}});};
const $=s=>document.querySelector(s),$$=s=>[...document.querySelectorAll(s)];
let curUrl="",pollTimer=null;
const urlIn=$("#url"),urlWrap=$("#urlWrap");
const calmScroll=matchMedia("(prefers-reduced-motion: reduce)").matches?"auto":"smooth";
const esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const ICON={play:'<path d="M7 4l12 8-12 8V4z" fill="currentColor" stroke="none"/>',
            stop:'<rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor" stroke="none"/>',
            share:'<path d="M12 16V4m0 0L8 8m4-4 4 4"/><path d="M5 14v4a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-4"/>'};

function detect(u){u=(u||"").toLowerCase();
 if(/youtu\.be\/|youtube\./.test(u))return"youtube";
 if(u.includes("tiktok.com"))return"tiktok";
 if(/(twitter|x)\.com/.test(u))return"x";
 return u.trim()?"other":null;}
function fmtDur(s){if(!s&&s!==0)return"";s=Math.round(s);const h=~~(s/3600),m=~~((s%3600)/60),x=s%60,p=n=>String(n).padStart(2,"0");return h?h+":"+p(m)+":"+p(x):m+":"+p(x);}
function ago(t){const s=Math.max(1,~~(Date.now()/1000-t));return s<60?"just now":s<3600?~~(s/60)+" min ago":s<86400?~~(s/3600)+" hr ago":~~(s/86400)+" days ago";}
const sizeStr=b=>b>1048576?(b/1048576).toFixed(1)+" MB":Math.max(1,~~(b/1024))+" KB";
function cookieCfg(){const b=$("#cookieBrowser"),f=$("#cookieFile");
 return {browser:(b&&b.value)||null,cookie_file:(f&&f.value.trim())||null};}

/* Copy and controls follow the device. On the phone there is no browser profile to
   read cookies from, and yt-dlp is baked into the APK and cannot update itself. */
$("#urlHint").textContent = CFG.android
  ? "Saved on this phone. Playlists download their first video."
  : "Press / to focus. Playlists download their first video.";
$("#toolsBox").innerHTML = (CFG.android ? "" : `
  <label class="tool-field"><span class="lbl">Browser cookies</span>
   <select id="cookieBrowser" class="sel">
    <option value="">None - public videos</option><option value="chrome">Chrome</option>
    <option value="edge">Edge</option><option value="firefox">Firefox</option>
    <option value="brave">Brave</option><option value="opera">Opera</option>
   </select></label>`) + `
  <label class="tool-field"><span class="lbl">Cookie file</span>
   <input id="cookieFile" class="cf" placeholder="Path to cookies.txt" spellcheck="false"></label>`
  + (CFG.android ? "" : `
  <div><button type="button" id="updateBtn" class="upbtn">Update yt-dlp</button>
   <span id="upStatus" role="status" aria-live="polite"></span></div>`);

$("#supportLink").href = SUPPORT_URL;

const bar=$("#appbar");
addEventListener("scroll",()=>bar.classList.toggle("stuck",scrollY>4),{passive:true});

urlIn.addEventListener("input",()=>{
 urlIn.removeAttribute("aria-invalid");
 const p=detect(urlIn.value);
 if(p)urlWrap.dataset.plat=p;else delete urlWrap.dataset.plat;
});
if(!CFG.android)addEventListener("keydown",e=>{
 if(e.key==="/"&&document.activeElement!==urlIn){e.preventDefault();urlIn.focus();}});

function showErr(m){const e=$("#errMsg");e.textContent=m;e.classList.remove("hidden");urlIn.setAttribute("aria-invalid","true");}
function hideErr(){$("#errMsg").classList.add("hidden");urlIn.removeAttribute("aria-invalid");}
function clearPoll(){if(pollTimer)clearInterval(pollTimer),pollTimer=null;}
function chipsBusy(b){const c=$(".chips");c&&c.classList.toggle("busy",b);}

$("#grabForm").addEventListener("submit",async e=>{
 e.preventDefault();const url=urlIn.value.trim();if(!url){showErr("Paste a link first.");return;}
 hideErr();clearPoll();
 const btn=$("#goBtn"),lbl=btn.querySelector("span");
 btn.disabled=true;lbl.textContent="Checking";
 try{
  const r=await api("/api/probe",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({url,...cookieCfg()})});
  const d=await r.json();if(!d.ok)throw new Error(d.error||"Could not read that link.");
  curUrl=url;renderResult(d);
 }catch(err){showErr(err.message)}
 finally{btn.disabled=false;lbl.textContent="Get video";}
});

function renderResult(d){
 const names={youtube:"YouTube",tiktok:"TikTok",x:"X",other:"Video"};
 const res=$("#result");
 res.className=d.platform||"other";
 res.classList.add("card");
 res.innerHTML=`<div class="card-body">
   ${d.thumbnail?`<img src="${esc(d.thumbnail)}" alt="" onerror="this.remove()">`:""}
   <div class="card-info">
    <span class="src">${names[d.platform]||"Video"}${d.playlist?" &middot; first in playlist":""}</span>
    <h2>${esc(d.title)}</h2>
    <p class="meta">${esc(d.uploader||"")}${d.duration?" &middot; "+fmtDur(d.duration):""}</p>
   </div></div>
  <div class="chips">
   ${[["auto","Best"],["1080","1080p"],["720","720p"],["480","480p"],["mp3","MP3"]]
     .map(([q,l])=>`<button type="button" class="chip" data-q="${q}">${l}</button>`).join("")}
  </div>
  <div id="job" class="job hidden"></div>`;
 res.scrollIntoView({behavior:calmScroll,block:"nearest"});
 $$("#result .chip").forEach(c=>c.addEventListener("click",()=>startJob(c.dataset.q,c)));
}

function jobHtml(pct,text,ind){
 return `<span class="pct">${ind?"":Math.round(pct)+"%"}</span>
  <div class="bar${ind?" ind":""}" role="progressbar" aria-label="Download progress"
       aria-valuemin="0" aria-valuemax="100"${ind?"":` aria-valuenow="${Math.round(pct)}"`}>
   <i style="width:${pct}%"></i></div>
  <span class="jobtext" role="status">${esc(text)}</span>`;
}

async function startJob(q,btn){
 $$("#result .chip").forEach(c=>c.classList.remove("picked"));
 btn.classList.add("picked");chipsBusy(true);
 const jb=$("#job");jb.className="job";jb.innerHTML=jobHtml(0,"Starting",true);
 try{
  const r=await api("/api/download",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({url:curUrl,quality:q,...cookieCfg()})});
  const d=await r.json();if(!d.ok)throw new Error(d.error);poll(d.job_id);
 }catch(e){jobFail(e.message)}
}

function poll(id){
 clearPoll();
 pollTimer=setInterval(async()=>{
  let j;try{j=await (await api("/api/job/"+id)).json();}catch{return;}
  const jb=$("#job");if(!jb)return;
  if(j.status==="probing")          jb.innerHTML=jobHtml(0,"Reading details",true);
  else if(j.status==="downloading") jb.innerHTML=jobHtml(j.pct||0,`${j.speed||""}${j.eta?" &middot; "+j.eta+" left":""}`.trim()||"Downloading");
  else if(j.status==="processing")  jb.innerHTML=jobHtml(100,"Finishing",true);
  else if(j.status==="done"){
   clearPoll();chipsBusy(false);jb.className="job done";
   jb.innerHTML=`<span class="pct">Done</span><div class="dtext" role="status">Saved ${esc(j.file||"")}</div>`;
   refreshFiles(true);
  }
  else if(j.status==="error"){clearPoll();chipsBusy(false);jobFail(j.error)}
 },700);
}
function jobFail(msg){
 const jb=$("#job");if(!jb)return;jb.className="job fail";
 jb.innerHTML=`<span class="pct">Failed</span><div class="dtext" role="status">${esc(msg)}</div>`;
}

async function refreshFiles(flash){
 let d;try{d=await (await api("/api/files")).json();}catch{return;}
 const items=d.files||[];
 $("#saveMeta").textContent=items.length?`${items.length} file${items.length===1?"":"s"}`:"";
 $("#recentCount").textContent=items.length?items.length:"";
 const ul=$("#recentList");ul.innerHTML="";
 items.forEach((f,i)=>{
  const li=document.createElement("li");
  const fresh=flash&&i===0&&Date.now()/1000-f.mtime<8;
  li.className="grab "+(f.platform||"other")+(fresh?" fresh":"");
  if(fresh)setTimeout(()=>li.classList.remove("fresh"),1800);
  const disp=f.name.replace(/^(YT|TT|X) /,"").replace(/\.[a-z0-9]+$/i,"");
  li.innerHTML=`<div class="grow"><b>${esc(disp)}</b><span class="sub">${sizeStr(f.size)} &middot; ${ago(f.mtime)}</span></div>`;

  const play=document.createElement("button");
  play.className="rowbtn";play.type="button";
  play.setAttribute("aria-label","Preview "+disp);
  play.innerHTML=`<svg viewBox="0 0 24 24">${ICON.play}</svg>`;
  play.addEventListener("click",()=>{
   let v=li.querySelector("video");
   if(v){v.remove();play.innerHTML=`<svg viewBox="0 0 24 24">${ICON.play}</svg>`;play.setAttribute("aria-label","Preview "+disp);return;}
   play.innerHTML=`<svg viewBox="0 0 24 24">${ICON.stop}</svg>`;play.setAttribute("aria-label","Close preview of "+disp);
   v=document.createElement("video");v.controls=true;v.src=withTok("/file/"+encodeURIComponent(f.name));li.appendChild(v);
  });
  li.appendChild(play);

  if(CFG.android&&window.Android&&window.Android.share){
   const sh=document.createElement("button");
   sh.className="rowbtn";sh.type="button";
   sh.setAttribute("aria-label","Save or share "+disp);
   sh.innerHTML=`<svg viewBox="0 0 24 24">${ICON.share}</svg>`;
   sh.addEventListener("click",()=>window.Android.share(f.name));
   li.appendChild(sh);
  }
  ul.appendChild(li);
 });
 $("#emptyRecent").style.display=items.length?"none":"block";
}

const upBtn=$("#updateBtn");
if(upBtn)upBtn.addEventListener("click",async()=>{
 const status=$("#upStatus");upBtn.classList.add("busy");status.textContent="Updating";
 try{
  const response=await api("/api/update",{method:"POST"});
  if(!response.ok)throw new Error((await response.json()).error||"Update failed");
  const timer=setInterval(async()=>{
   try{
    const state=await (await api("/api/update")).json();
    if(state.status==="done"){clearInterval(timer);upBtn.classList.remove("busy");status.textContent="Updated. Restart SNAG.";}
    else if(state.status==="error"){clearInterval(timer);upBtn.classList.remove("busy");status.textContent=state.log||"Update failed";}
   }catch{}
  },1500);
 }catch(error){upBtn.classList.remove("busy");status.textContent=error.message;}
});

refreshFiles(false);
</script>
</body></html>"""

# ---------------------------------------------------------------- CLI + main
def cli_download(url, quality, browser=None, cookiefile=None):
    plat, prefix = detect_platform(url)
    cparams = cookie_params(browser, cookiefile)
    target, info, _ = resolve(url, cparams)
    if quality == "mp3":
        fmt = "bestaudio/b"
        pp = [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3",
               "preferredquality": "192"}]
    else:
        fmt, pp = QUALITIES[quality], []
    opts = {"format": fmt, "postprocessors": pp,
            "outtmpl": str(OUTDIR) + os.sep + (prefix + " " if prefix else "") + "%(title).80s [%(id)s].%(ext)s",
            "merge_output_format": "mp4", "noplaylist": True}
    opts.update(base_opts())
    opts.update(cparams)
    print(f"[snag] {info.get('title','?')}  ({quality})")
    try:
        with yt_dlp.YoutubeDL(opts) as ydl: ydl.download([target])
    except DownloadError as e:
        print("[error]", friendly(e, plat)); sys.exit(1)
    print(f"[ok] saved to {OUTDIR}")

def main():
    global OUTDIR
    ap = argparse.ArgumentParser(description="SNAG — grab videos from YouTube / TikTok / X(Twitter) and 1000+ more sites.")
    ap.add_argument("url", nargs="?", help="video URL (omit to open the web app)")
    ap.add_argument("-q", "--quality", default="auto", choices=["auto","1080","720","480","mp3"])
    ap.add_argument("-o", "--out", default=str(Path.cwd()/"snag_downloads"), help="download folder")
    ap.add_argument("--cookies-from-browser", choices=["chrome", "edge", "firefox", "brave", "opera"])
    ap.add_argument("--cookies-file", help="path to a Netscape-format cookies.txt file")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()

    OUTDIR = Path(a.out).expanduser(); OUTDIR.mkdir(parents=True, exist_ok=True)
    if a.url: cli_download(a.url, a.quality, a.cookies_from_browser, a.cookies_file); return

    try: srv = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    except OSError: print(f"[!] port {a.port} is busy — try --port 8766"); sys.exit(1)

    url = f"http://localhost:{a.port}"
    print("  SNAG is running  -> " + url)
    print(f"     saves to: {os.path.relpath(OUTDIR)}   (Ctrl+C quits)")
    if not a.no_browser: threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try: srv.serve_forever()
    except KeyboardInterrupt: print("\nbye.")

# ---------------------------------------------------------------- Android entry point
def serve(port=0, outdir=None, ffmpeg_dir=None, lib_dir=None):
    """Start the web UI on a daemon thread and return its base URL.

    Called from MainActivity.kt through Chaquopy. port=0 lets the OS pick a free
    port. ffmpeg_dir holds the ffmpeg/ffprobe symlinks, lib_dir the shared
    libraries they need (ffmpeg is dynamically linked).
    """
    global OUTDIR, FFMPEG_DIR, TOKEN, SERVER_URL
    with SERVE_LOCK:
        if SERVER_URL:
            return SERVER_URL
        return _start_server(port, outdir, ffmpeg_dir, lib_dir)

def _start_server(port, outdir, ffmpeg_dir, lib_dir):
    """Bind the server. Only ever called with SERVE_LOCK held."""
    global OUTDIR, FFMPEG_DIR, TOKEN, SERVER_URL
    if outdir:
        OUTDIR = Path(outdir).expanduser()
    OUTDIR.mkdir(parents=True, exist_ok=True)

    # Any app on the phone can open a socket to 127.0.0.1, so the API is only as
    # private as this token. It is handed to the WebView in the start URL and
    # never leaves the device.
    TOKEN = secrets.token_urlsafe(32)

    if lib_dir:
        prev = os.environ.get("LD_LIBRARY_PATH")
        os.environ["LD_LIBRARY_PATH"] = lib_dir + (os.pathsep + prev if prev else "")
    if ffmpeg_dir:
        FFMPEG_DIR = ffmpeg_dir

    if ANDROID:
        # yt-dlp writes its cache and .part files via HOME / XDG / TMPDIR, none
        # of which point anywhere writable inside an APK unless we say so.
        base = OUTDIR.parent
        for var, sub_ in (("HOME", ""), ("XDG_CACHE_HOME", "cache"), ("TMPDIR", "tmp")):
            d = base / sub_ if sub_ else base
            d.mkdir(parents=True, exist_ok=True)
            os.environ[var] = str(d)

    srv = ThreadingHTTPServer(("127.0.0.1", int(port)), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    SERVER_URL = f"http://127.0.0.1:{srv.server_address[1]}/?t={TOKEN}"
    return SERVER_URL

if __name__ == "__main__":
    main()
