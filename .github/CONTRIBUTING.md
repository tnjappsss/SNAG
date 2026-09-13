# Contributing

## Two things that will catch you out

**`snag.py` at the repo root is the source. The Android copy is generated.**
`app/src/main/python/snag.py` is produced by `tools/patch_snag.py` and any edit to
it is overwritten. Change the root file, then regenerate:

```bash
python tools/patch_snag.py
```

The script applies eight patches, each anchored on an exact snippet, so a rename
or reformat upstream fails the regeneration loudly instead of applying half of it.

**The FFmpeg payload is not in the repo.** Fetch it once before building:

```bash
python tools/package_ffmpeg.py
```

It downloads two AARs from Maven Central, checks them against pinned SHA-1s, walks
FFmpeg's transitive dependency closure and writes the libraries into `assets/` and
the executables into `jniLibs/`. The Gradle build fails with instructions if you
skip it.

## Building

```bash
./gradlew assembleDebug
```

You need JDK 17, the Android SDK with the API 35 platform and build-tools 35, and
a local CPython **3.10 to 3.14** for Chaquopy's pip. CPython is taken from `PATH`;
point at a specific one with `chaquopy.python=` in `local.properties`.

## Constraints worth knowing before you change things

- **arm64-v8a only.** Chaquopy publishes `brotli` and `pycryptodomex` wheels for
  CPython 3.12 on 64-bit only, so adding `armeabi-v7a` breaks the build.
- **yt-dlp must be installed as `yt-dlp[default]`.** The base package declares
  zero required dependencies; requests, brotli, pycryptodomex, certifi and the
  rest live in its `default` extra.
- **play-services-ads is pinned to 24.x.** 25.x is compiled with Kotlin 2.3
  metadata, which the project's Kotlin 2.1.20 cannot read.
- **TikTok needs a browser User-Agent on Android.** With yt-dlp's default headers
  TikTok returns a 537-byte "Site Maintenance" stub, from the phone only.
- **The loopback API is token-authenticated.** If you add a route, split the query
  string off the path before matching it, or the token parameter will send every
  request to the 404 branch.
- **`getExternalFilesDir()` must not be called in a property initialiser.** The
  Context is not attached yet.

## Testing a change

There is no test suite. Build, install, and put a real link through the app:

```bash
./gradlew assembleDebug && adb install -r app/build/outputs/apk/debug/app-debug.apk
```

Check a download completes and the file lands in the Downloads list. If you
touched routing or auth, exercise a **POST**, not just a GET. Keep the app on
screen: Android cuts network access to backgrounded apps and yt-dlp then fails
with DNS errors that look like a bug in the code.

## Licence

Contributions are under GPLv3, with the additional permission in
[LICENSE-EXCEPTION.md](../docs/LICENSE-EXCEPTION.md) covering the proprietary
Google ad SDKs.
