# Third-party components

## FFmpeg 7.1.1 — GPL v3

The APK bundles an FFmpeg build for `arm64-v8a`: the `ffmpeg` and `ffprobe`
executables in `app/src/main/jniLibs/`, and 78 shared libraries in
`app/src/main/assets/ffmpeg-arm64-v8a.zip`.

Neither is committed to this repository. `tools/package_ffmpeg.py` downloads them
from Maven Central and verifies each archive against the SHA-1 that Maven Central
publishes, pinned in the script:

| Artifact | Version | SHA-1 |
| --- | --- | --- |
| `io.github.junkfood02.youtubedl-android:ffmpeg` | 0.18.1 | `b8895caf6946d3c1d35b7df0993c19dcef5956c6` |
| `io.github.junkfood02.youtubedl-android:library` | 0.18.1 | `9db4b55f3aa38a284218a8e39bfdc5949f8187e4` |

That is a Termux build of FFmpeg 7.1.1, configured with `--enable-gpl
--enable-version3`, so **it is covered by the GNU General Public License v3**. Its
own configuration string, readable with `ffmpeg -version`, records the full build
options.

If you redistribute the APK you must comply with the GPL v3 for this component:
include the licence text and offer the corresponding source. FFmpeg source is at
<https://ffmpeg.org/download.html>; the Termux packaging that produced this
specific build is at <https://github.com/termux/termux-packages>.

SNAG invokes `ffmpeg` as a separate process through yt-dlp, rather than linking
against it. The usual reading is that this is aggregation rather than a derivative
work, so it does not by itself impose the GPL on SNAG's own code. That is not
legal advice.

## Chaquopy — MIT

The Python runtime and Gradle plugin (`com.chaquo.python` 17.0.0) have been free
and open source under the MIT licence since version 12.0.1. No copyleft
obligation. <https://github.com/chaquo/chaquopy>

## yt-dlp — Unlicense (public domain)

Installed at build time by Chaquopy's pip, together with its `default` extra.
<https://github.com/yt-dlp/yt-dlp>

Its `default` extra pulls in, among others:

| Package | Licence |
| --- | --- |
| `requests`, `urllib3`, `certifi` | Apache 2.0 / MIT / MPL 2.0 |
| `Brotli` | MIT |
| `pycryptodomex` | BSD 2-Clause + public domain |
| `mutagen` | GPL v2 or later |
| `websockets` | BSD 3-Clause |

Note that `mutagen` is GPL v2+. It is used by yt-dlp for audio metadata.

## Google Mobile Ads SDK and User Messaging Platform - proprietary

`com.google.android.gms:play-services-ads` and
`com.google.android.ump:user-messaging-platform` are proprietary Google libraries,
governed by the Google APIs Terms of Service rather than an open source licence.

They are linked into the app, which the GPL would normally forbid. SNAG therefore
carries an additional permission under GPL section 7 allowing exactly that
combination; see [LICENSE-EXCEPTION.md](LICENSE-EXCEPTION.md).

This is why SNAG is not eligible for F-Droid, which requires every component to be
free software.

## AndroidX

`androidx.appcompat` and `androidx.core` are Apache 2.0.
