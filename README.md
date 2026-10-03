# SNAG

Save videos from YouTube, TikTok, X and around a thousand other sites straight to
your Android phone. No account, no ads, no server: the download happens on the
device and the file never leaves it.

![Licence](https://img.shields.io/badge/licence-GPL--3.0-blue)
![Android](https://img.shields.io/badge/Android-7.0%2B-brightgreen)
![ABI](https://img.shields.io/badge/ABI-arm64--v8a-lightgrey)

SNAG bundles a real [yt-dlp](https://github.com/yt-dlp/yt-dlp) and a real
[FFmpeg](https://ffmpeg.org) inside the APK, driven by a small local web UI.
Because they are the genuine tools rather than a reimplementation, it handles HD
stream merging, MP3 extraction and every site yt-dlp supports.

| | | | |
| :---: | :---: | :---: | :---: |
| <img src="docs/screenshot-1-paste.png" width="190" alt="Paste a link"> | <img src="docs/screenshot-2-choose.png" width="190" alt="Choose a quality"> | <img src="docs/screenshot-3-downloading.png" width="190" alt="Downloading"> | <img src="docs/screenshot-4-saved.png" width="190" alt="Saved"> |
| Paste a link | Pick a quality | Download | Saved on the phone |

## Install

Download the APK from [Releases](https://github.com/tnjappsss/SNAG/releases) and
open it on your phone. Android will ask you to allow installs from this source.

To check a download is genuine:

```bash
apksigner verify --print-certs app-release.apk
```

```
Signer #1 certificate SHA-256: 2039afdc2d7f034f90e948aa76bd50988dccd618cf31d1200692961c82258d11
```

**Requirements:** Android 7.0 (API 24) or later, **arm64-v8a** only. That covers
essentially every phone sold in the last decade, but excludes 32-bit devices,
emulators and ChromeOS.

### Not on Google Play

It cannot be. YouTube's Developer Policies forbid apps that let people download
videos for offline play outside YouTube Premium, and Google Play separately bars
apps that induce copyright infringement. Every yt-dlp based Android app is
distributed outside Play for the same reason.

## Using it

Paste a link and pick a quality, or share a link to SNAG directly from YouTube,
TikTok or X and the download starts on its own.

Files land in `Android/data/com.snag.app/files/SNAG/`. Android 11 and later hide
that folder from the Files app, so use the **⇪** button beside each download to
send a video to your gallery or another app. That goes through a `FileProvider`
declared in `res/xml/file_paths.xml`.

Keep SNAG on screen while a download runs. Android cuts network access to
backgrounded apps, which surfaces as `Failed to resolve` DNS errors from yt-dlp.
The app holds the screen awake to reduce the chance of that.

Cookies from a logged-in browser are not reachable from inside an APK, so private
or age-restricted videos need a `cookies.txt` file, which you can point at under
Options.

## On a PC

`snag.py` is the same program the app runs, and it works on its own.

**Windows:** download the exe (about 100 MB) from
[Releases](https://github.com/tnjappsss/SNAG/releases) and run it. Python,
yt-dlp and FFmpeg are all inside it, so nothing has to be installed and HD
merging and MP3 extraction work out of the box. It opens the same web UI at
<http://localhost:8765>. The window it runs in stays open while downloads run;
closing it or pressing Ctrl+C stops SNAG.

Windows SmartScreen may warn the first time, because the exe is not signed with
a paid certificate. Choose **More info**, then **Run anyway**, or check the
SHA-256 on the release first.

**Anywhere else:** Python 3.8 or newer and `pip install yt-dlp` are all it needs.

```bash
python snag.py
```

FFmpeg is needed for MP3 extraction and HD stream merging. Install it with
`winget install ffmpeg`, `brew install ffmpeg` or `apt install ffmpeg`. The exe
and the APK both carry their own copy, so this only applies when running the
script directly.

It also works without the UI:

```bash
python snag.py "https://www.tiktok.com/@user/video/123" -q 720
python snag.py "<url>" -q mp3 -o ~/Music
python snag.py "<url>" --cookies-from-browser chrome
```

Unlike the APK, the desktop version can read cookies straight from your browser,
so private and age-restricted videos work without exporting anything.

To build the exe yourself: `pip install pyinstaller`, then
`python tools/build_exe.py`. It writes `dist/SNAG.exe`.

## Community

- [XDA thread](https://xdaforums.com/t/app-7-0-open-source-snag-yt-dlp-and-ffmpeg-in-an-apk-downloads-run-on-your-phone.4803158/)
- [r/SNAG_official](https://www.reddit.com/r/SNAG_official)

## Licence

GNU General Public License v3.0, see [LICENSE](LICENSE), with an additional
permission allowing the proprietary Google ad SDKs to be linked in
([LICENSE-EXCEPTION.md](docs/LICENSE-EXCEPTION.md)). The bundled FFmpeg is itself
GPLv3, and [THIRD_PARTY.md](docs/THIRD_PARTY.md) covers every third-party component
and its licence.
