"""Create a GitHub release and upload its assets.

    python tools/make_release.py v1.4 "SNAG 1.4" notes.md file1 [file2 ...]

The token is read from the git credential helper, never from a file or argv.
"""
import json
import mimetypes
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO = "tnjappsss/SNAG"
API = "https://api.github.com"
UPLOADS = "https://uploads.github.com"

TYPES = {
    ".apk": "application/vnd.android.package-archive",
    ".exe": "application/vnd.microsoft.portable-executable",
    ".sha256": "text/plain",
}


def token():
    out = subprocess.run(["git", "credential", "fill"], input="protocol=https\nhost=github.com\n\n",
                         capture_output=True, text=True, check=True).stdout
    for line in out.splitlines():
        if line.startswith("password="):
            return line[len("password="):]
    sys.exit("no stored GitHub credential found")


def call(url, tok, data=None, ctype="application/json", method=None):
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", "Bearer " + tok)
    req.add_header("Accept", "application/vnd.github+json")
    if data is not None:
        req.add_header("Content-Type", ctype)
    try:
        with urllib.request.urlopen(req) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit("%s %s\n%s" % (e.code, url.split("?")[0], e.read().decode()[:400]))


def main():
    tag, name, notes_path, *files = sys.argv[1:]
    tok = token()

    body = Path(notes_path).read_text(encoding="utf-8")
    rel = call("%s/repos/%s/releases" % (API, REPO), tok,
               json.dumps({"tag_name": tag, "target_commitish": "main", "name": name,
                           "body": body, "draft": False, "prerelease": False}).encode())
    print("created", rel["html_url"])

    for f in files:
        p = Path(f)
        ctype = TYPES.get(p.suffix) or mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        print("uploading %-34s %8.1f MB ..." % (p.name, p.stat().st_size / 1048576), end="", flush=True)
        a = call("%s/repos/%s/releases/%d/assets?name=%s" % (UPLOADS, REPO, rel["id"], p.name),
                 tok, p.read_bytes(), ctype)
        print(" %s" % a["state"])

    final = call("%s/repos/%s/releases/%d" % (API, REPO, rel["id"]), tok)
    print("\n%s" % final["html_url"])
    for a in final["assets"]:
        print("  %-34s %10d bytes" % (a["name"], a["size"]))


if __name__ == "__main__":
    main()
