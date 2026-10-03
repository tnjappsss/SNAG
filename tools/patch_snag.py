"""Generate the Android copy of snag.py from the desktop original.

Every patch is anchored on an exact snippet and fails loudly if the desktop file
drifts, so this can be re-run after editing Desktop/snag.py.

The desktop file already carries the ANDROID flag and the device-aware page, so
what is left here is the handful of things that only make sense inside the APK.
"""
import sys, pathlib

REPO = pathlib.Path(__file__).resolve().parent.parent
# snag.py at the repo root is the canonical source; the Android copy is generated.
SRC = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / "snag.py"
DST = REPO / "app" / "src" / "main" / "python" / "snag.py"

s = SRC.read_text(encoding="utf-8")
applied = []

def sub(anchor, new, label):
    global s
    if anchor not in s:
        sys.exit(f"ANCHOR MISSING [{label}]:\n{anchor[:200]}")
    if s.count(anchor) != 1:
        sys.exit(f"ANCHOR NOT UNIQUE ({s.count(anchor)}x) [{label}]")
    s = s.replace(anchor, new)
    applied.append(label)

# 1 -- ffmpeg location + a save-folder label that survives external storage ----
sub(
'''ANDROID = (hasattr(sys, "getandroidapilevel")
           or "ANDROID_ROOT" in os.environ
           or "ANDROID_DATA" in os.environ)''',
'''ANDROID = (hasattr(sys, "getandroidapilevel")
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
        return str(OUTDIR)''',
"android-extras")

# 2 -- don't blame a missing ffmpeg when we ship one --------------------------
sub(
'    if "ffmpeg" in s.lower() and not shutil.which("ffmpeg"):',
'    if "ffmpeg" in s.lower() and not shutil.which("ffmpeg") and not FFMPEG_DIR:',
"ffmpeg-message")

# 3 -- /api/files uses the safe label -----------------------------------------
sub(
'return self._json({"outdir": os.path.relpath(OUTDIR), "files": list_files()})',
'return self._json({"outdir": outdir_label(), "files": list_files()})',
"files-label")

# 4 -- pip self-update is impossible inside an APK ----------------------------
sub(
'''def do_update():
    def update():''',
'''def do_update():
    if ANDROID:
        UPDATE.update(status="error",
                      log="yt-dlp is baked into the APK and cannot update itself. "
                          "Rebuild the app to pick up a newer yt-dlp.")
        return
    def update():''',
"update-guard")

# 5 -- Android-only yt-dlp options --------------------------------------------
sub(
'''def resolve(url, cparams=None):
    """Return a single-video URL + its info dict."""
    opts = {"quiet": True, "no_warnings": True}
    opts.update(cparams or {})''',
'''BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
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
    opts.update(cparams or {})''',
"base-opts")

sub(
'''            "progress_hooks": [make_hook(JOBS[jid])],
        }
        opts.update(cparams)''',
'''            "progress_hooks": [make_hook(JOBS[jid])],
        }
        opts.update(base_opts())
        opts.update(cparams)''',
"base-opts-runjob")

sub(
'''            "merge_output_format": "mp4", "noplaylist": True}
    opts.update(cparams)''',
'''            "merge_output_format": "mp4", "noplaylist": True}
    opts.update(base_opts())
    opts.update(cparams)''',
"base-opts-cli")

# 6 -- serve() entry point called from MainActivity.kt ------------------------
sub(
'''if __name__ == "__main__":
    main()''',
'''# ---------------------------------------------------------------- Android entry point
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
    main()''',
"serve-fn")

DST.parent.mkdir(parents=True, exist_ok=True)
with open(DST, "w", encoding="utf-8", newline="\n") as f:
    f.write(s)
print("applied:", ", ".join(applied))
print("lines:", len(s.splitlines()), "->", DST)
