# Security

## Reporting a vulnerability

Use GitHub's private reporting: **Security → Report a vulnerability** on this
repository. That keeps the report private until there is a fix. Please don't open
a public issue for something exploitable.

Expect a reply within a week. This is a one-person project, so that is a best
effort rather than a guarantee.

## What is worth reporting

SNAG runs a Python HTTP server on `127.0.0.1` inside the app, and on Android the
loopback interface is **not** private: any installed app holding the `INTERNET`
permission can connect to it. That server is therefore the most interesting part
of the attack surface.

It is protected by a token minted per launch, which every request must present as
an `X-Snag-Token` header or a `?t=` query parameter, compared with
`secrets.compare_digest`. `GET /` is protected too, so the token cannot be read
out of the page. Anything that gets past that, reads a file outside the download
directory, or lets another app queue a download, is worth reporting.

Also of interest:

- Path traversal through `/file/`
- Anything that lets page content reach the `ShareBridge` JavaScript interface
  with a path outside the download directory
- Weaknesses in how the bundled ffmpeg is unpacked or invoked

## What is out of scope

- **yt-dlp extractor breakage.** A site changing its layout is not a security
  issue. Use the issue template.
- **Downloading copyrighted material.** That is a question about how people use
  the app, not a vulnerability.
- **The bundled FFmpeg and yt-dlp themselves.** Report those upstream; this
  project only packages them.
- Reports that require physical access to an unlocked phone, or an attacker who
  already has root.

## Supported versions

Only the most recent release. yt-dlp and FFmpeg are baked into the APK and cannot
update themselves, so older builds drift out of date and are not patched.
