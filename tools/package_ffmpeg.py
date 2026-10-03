"""Fetch ffmpeg for Android arm64 and lay it into the app.

The APK needs two things: the ffmpeg/ffprobe executables (which go in jniLibs,
because since Android 10 the native library directory is the only place an app is
allowed to exec from) and the ~78 shared libraries they are linked against (which
ride along in assets and get unpacked on first launch).

Both come out of the youtubedl-android AARs on Maven Central, the same ones the
Seal app uses. Each download is checked against the SHA-1 pinned below, which is
the digest Maven Central publishes alongside the artifact.

Only ffmpeg's actual transitive closure is shipped, and each library is stored
under its DT_SONAME so the dynamic linker finds it with no symlinks at runtime.

Run from anywhere:  python tools/package_ffmpeg.py
"""
import collections, hashlib, io, os, pathlib, struct, sys, urllib.request, zipfile

REPO = pathlib.Path(__file__).resolve().parent.parent
MAIN = REPO / "app" / "src" / "main"
ABI = "arm64-v8a"

BASE = "https://repo1.maven.org/maven2/io/github/junkfood02/youtubedl-android"
VERSION = "0.18.1"
ARTIFACTS = {
    "ffmpeg":  "b8895caf6946d3c1d35b7df0993c19dcef5956c6",
    "library": "9db4b55f3aa38a284218a8e39bfdc5949f8187e4",
}


def fetch(name: str, sha1: str) -> zipfile.ZipFile:
    cache = REPO / "build" / "ffmpeg-src"
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / f"{name}-{VERSION}.aar"
    if not path.exists():
        url = f"{BASE}/{name}/{VERSION}/{name}-{VERSION}.aar"
        print(f"downloading {url}")
        urllib.request.urlretrieve(url, path)
    got = hashlib.sha1(path.read_bytes()).hexdigest()
    if got != sha1:
        path.unlink(missing_ok=True)
        sys.exit(f"SHA-1 mismatch for {name}: expected {sha1}, got {got}")
    print(f"  {name}-{VERSION}.aar sha1 ok ({path.stat().st_size:,} bytes)")
    return zipfile.ZipFile(path)


def dyn(data: bytes):
    """Return (DT_NEEDED sonames, DT_SONAME) for a 64-bit little-endian ELF."""
    if data[:4] != b"\x7fELF" or data[4] != 2:
        return [], None
    e_phoff, = struct.unpack_from("<Q", data, 0x20)
    e_phentsize, e_phnum = struct.unpack_from("<HH", data, 0x36)
    dyn_off = dyn_sz = None
    loads = []
    for k in range(e_phnum):
        o = e_phoff + k * e_phentsize
        p_type, = struct.unpack_from("<I", data, o)
        p_off, p_vaddr, _p_paddr, p_filesz = struct.unpack_from("<QQQQ", data, o + 0x08)
        if p_type == 2:
            dyn_off, dyn_sz = p_off, p_filesz
        elif p_type == 1:
            loads.append((p_vaddr, p_off, p_filesz))
    if dyn_off is None:
        return [], None

    def v2o(v):
        for vaddr, off, fsz in loads:
            if vaddr <= v < vaddr + fsz:
                return off + (v - vaddr)

    needed, soname_idx, strtab = [], None, None
    for k in range(dyn_sz // 16):
        tag, val = struct.unpack_from("<QQ", data, dyn_off + k * 16)
        if tag == 0:
            break
        if tag == 1:
            needed.append(val)
        elif tag == 5:
            strtab = val
        elif tag == 14:
            soname_idx = val
    if strtab is None:
        return [], None
    base = v2o(strtab)
    if base is None:
        return [], None

    def s(i):
        end = data.index(b"\x00", base + i)
        return data[base + i:end].decode()

    return [s(i) for i in needed], (s(soname_idx) if soname_idx is not None else None)


def main():
    ff_aar = fetch("ffmpeg", ARTIFACTS["ffmpeg"])
    lib_aar = fetch("library", ARTIFACTS["library"])

    ff_libs = zipfile.ZipFile(io.BytesIO(ff_aar.read(f"jni/{ABI}/libffmpeg.zip.so")))
    # libc++_shared, libandroid-support, libcrypto.so.3 and friends are Termux
    # runtime libraries that are NOT in the ffmpeg AAR; they live in the other one.
    py_libs = zipfile.ZipFile(io.BytesIO(lib_aar.read(f"jni/{ABI}/libpython.zip.so")))

    def index(z):
        return {i.filename: i for i in z.infolist() if not i.filename.endswith("/")}

    FF, PY = index(ff_libs), index(py_libs)

    def is_link(info):
        return (info.external_attr >> 16) & 0xF000 == 0xA000

    def resolve(table, z, soname):
        p, guard = "usr/lib/" + soname, 0
        while p in table and is_link(table[p]) and guard < 10:
            guard += 1
            target = z.read(table[p]).decode()
            p = os.path.normpath(os.path.join(os.path.dirname(p), target)).replace("\\", "/")
        return p if p in table else None

    keep, queue, seen, from_system = {}, collections.deque(), set(), set()
    for exe in ("libffmpeg.so", "libffprobe.so"):
        queue.extend(dyn(ff_aar.read(f"jni/{ABI}/{exe}"))[0])

    while queue:
        soname = queue.popleft()
        if soname in seen:
            continue
        seen.add(soname)
        data = None
        p = resolve(FF, ff_libs, soname)
        if p:
            data = ff_libs.read(FF[p])
        else:
            p = resolve(PY, py_libs, soname)
            if p:
                data = py_libs.read(PY[p])
        if data is None:
            from_system.add(soname)
            continue
        needed, real_soname = dyn(data)
        keep[real_soname or soname] = data
        for n in needed:
            if n not in seen:
                queue.append(n)

    print(f"from Android itself (not bundled): {', '.join(sorted(from_system))}")
    total = sum(len(v) for v in keep.values())
    print(f"libraries: {len(keep)}   uncompressed: {total:,} bytes")

    (MAIN / "assets").mkdir(parents=True, exist_ok=True)
    (MAIN / "jniLibs" / ABI).mkdir(parents=True, exist_ok=True)

    out = MAIN / "assets" / f"ffmpeg-{ABI}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name in sorted(keep):
            z.writestr(name, keep[name])
    print(f"wrote {out.relative_to(REPO)} ({out.stat().st_size:,} bytes)")

    for exe in ("libffmpeg.so", "libffprobe.so"):
        data = ff_aar.read(f"jni/{ABI}/{exe}")
        dest = MAIN / "jniLibs" / ABI / exe
        dest.write_bytes(data)
        print(f"wrote {dest.relative_to(REPO)} ({len(data):,} bytes)")


if __name__ == "__main__":
    main()
