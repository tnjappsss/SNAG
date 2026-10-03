#!/usr/bin/env python3
"""Build SNAG.exe, a single-file Windows build of snag.py with Python, yt-dlp
and FFmpeg inside it, so a PC user needs nothing installed at all.

    python tools/build_exe.py

Output lands in dist/SNAG.exe (about 100 MB). Needs pyinstaller:

    pip install pyinstaller

FFmpeg is not optional here: YouTube serves video and audio as separate streams,
so without it nearly every download fails on "requested merging of multiple
formats but ffmpeg is not installed". The APK bundles ffmpeg for the same
reason, see tools/package_ffmpeg.py.

The exe is not committed; it is attached to a GitHub release the same way the
APK is. This is a Windows build because that is where double-clicking matters;
elsewhere `python snag.py` is the normal route.
"""
import hashlib
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build" / "exe"
CACHE = ROOT / "build" / "ffmpeg-cache"

# Pinned so a build is reproducible and the payload is verifiable. To move to a
# newer FFmpeg, change both lines: the versioned packages/ URL never changes
# under you, unlike the ffmpeg-release-essentials.zip "latest" alias.
FFMPEG_URL = "https://www.gyan.dev/ffmpeg/builds/packages/ffmpeg-9.0.2-essentials_build.zip"
FFMPEG_SHA256 = "60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba"
WANTED = ("ffmpeg.exe", "ffprobe.exe")   # ffplay is another 100 MB we never call


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch_ffmpeg():
    """Return the directory holding a verified ffmpeg.exe and ffprobe.exe."""
    CACHE.mkdir(parents=True, exist_ok=True)
    binaries = [CACHE / name for name in WANTED]
    if all(b.exists() for b in binaries):
        print("ffmpeg: using cached copy in", CACHE)
        return binaries

    archive = CACHE / "ffmpeg.zip"
    if not archive.exists() or sha256(archive) != FFMPEG_SHA256:
        print("ffmpeg: downloading", FFMPEG_URL)
        urllib.request.urlretrieve(FFMPEG_URL, archive)

    got = sha256(archive)
    if got != FFMPEG_SHA256:
        archive.unlink()
        sys.exit(f"ffmpeg archive sha256 mismatch\n  expected {FFMPEG_SHA256}\n  got      {got}")
    print("ffmpeg: sha256 verified")

    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            name = Path(info.filename).name
            if name in WANTED:
                with z.open(info) as src, open(CACHE / name, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                print(f"  extracted {name}  {info.file_size / 1048576:.0f} MB")

    missing = [b.name for b in binaries if not b.exists()]
    if missing:
        sys.exit("ffmpeg archive did not contain: " + ", ".join(missing))
    return binaries


def main():
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        sys.exit("pyinstaller is not installed:  pip install pyinstaller")
    try:
        import yt_dlp  # noqa: F401
    except ImportError:
        sys.exit("yt-dlp is not installed:  pip install yt-dlp")

    binaries = fetch_ffmpeg()

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--windowed",
        "--add-data", f"{ROOT / 'docs' / 'logo.png'}{';' if sys.platform == 'win32' else ':'}.",
        "--name", "SNAG",
        "--icon", str(ROOT / "tools" / "snag.ico"),
        "--distpath", str(ROOT / "dist"),
        "--workpath", str(BUILD),
        "--specpath", str(BUILD),
        "--noconfirm",
        # yt-dlp reaches for its extractors by name, so they are invisible to
        # PyInstaller's import scan. Without this the exe builds and then fails
        # on every single URL.
        "--collect-all", "yt_dlp",
        # pulled in by yt-dlp's optional deps but never used by SNAG
        "--exclude-module", "test",
    ]
    for b in binaries:
        # "." puts them at the root of the unpacked bundle, which snag.py adds
        # to PATH when it detects a frozen build
        cmd += ["--add-binary", f"{b}{';' if sys.platform == 'win32' else ':'}."]
    cmd.append(str(ROOT / "snag.py"))

    print("\n" + " ".join(cmd) + "\n")
    subprocess.run(cmd, check=True, cwd=ROOT)

    exe = ROOT / "dist" / "SNAG.exe"
    print(f"\n{exe}  {exe.stat().st_size / 1048576:.1f} MB")
    print("sha256", sha256(exe))

    # the spec and work tree are regenerated every run and are pure noise
    shutil.rmtree(BUILD, ignore_errors=True)


if __name__ == "__main__":
    main()
