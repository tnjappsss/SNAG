"""Check whether the built exe leaks the build machine's identity.

A plain byte scan is not enough: PyInstaller stores most members zlib-compressed,
so this decompresses every member of the embedded archive and scans that too.
Each hit is printed with its surrounding bytes, because short needles match
innocent things (a contributor called Thomas in FFmpeg's credits, an upstream
build path baked into a prebuilt DLL) and only context tells them apart.

    python tools/scan_exe.py dist/SNAG.exe
"""
import re
import sys

BS = chr(92)  # backslash, kept out of literals so no shell can mangle it
NEEDLES = ['Thoma', 'miniconda', 'SnagAndroid', 'C:' + BS + 'Users',
           'thomasnordstrom', 'desktop-si5vi2i', 'S-1-5-21']

from PyInstaller.archive.readers import CArchiveReader  # noqa: E402

target = sys.argv[1]
blobs = [('raw exe', open(target, 'rb').read())]
arch = CArchiveReader(target)
for name in arch.toc:
    try:
        blobs.append((name, arch.extract(name)))
    except Exception as exc:                      # noqa: BLE001
        print('  could not read %s: %s' % (name, exc))
print('%s  %.0f MB  %d archive members' % (target, len(blobs[0][1]) / 1048576, len(blobs) - 1))

hits = 0
for needle in NEEDLES:
    nb = needle.encode('ascii')
    for label, blob in blobs:
        if label == 'raw exe':
            continue          # members cover it, and the raw copy double-counts
        for m in re.finditer(re.escape(nb), blob):
            hits += 1
            ctx = blob[max(0, m.start() - 45):m.end() + 45]
            ctx = re.sub(rb'[^\x20-\x7e]', b'.', ctx).decode('ascii')
            print('  %-20s %-46s %s' % (needle, label[:46], ctx))

print('\n%d raw hit(s). Read the context: a hit inside a third-party binary is '
      'upstream, not this machine.' % hits)
