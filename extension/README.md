# Send to SNAG

An unpacked Chrome/Edge extension for the SNAG Windows app. Start SNAG normally on its default port (8765) before using it.

## Install

1. Extract the extension ZIP to a permanent folder.
2. Open `chrome://extensions` in Chrome or `edge://extensions` in Edge.
3. Enable Developer mode and select Load unpacked.
4. Select the folder containing manifest.json, then pin Send to SNAG.
5. Run SNAG, visit a video page, and click Send this page to SNAG. Alternatively, right-click a link and select Send link to SNAG.
6. In the SNAG tab, select Best, 1080p, 720p, 480p, or MP3 to start downloading.

## Behavior and privacy

The extension adds a SNAG button beside the controls on desktop YouTube watch pages, and a floating SNAG button on X, Instagram and TikTok, including their feeds. On Vimeo, Twitch, SoundCloud and Reddit it appears on a video page but not on a feed. It handles navigation between videos and re-creates the button if YouTube replaces the controls. Shorts and embedded players are not supported. Click the button and choose Best available, 1080p, 720p, 480p, or Audio MP3. The download starts directly in SNAG without opening another tab. SNAG saves the file to snag_downloads beside the exe, or wherever you point it with Choose download folder in the tray menu. A start confirmation means the job was queued, not that it has completed; use the SNAG interface to inspect progress and errors. Resolution choices are maximum heights, subject to the source video. The popup and right-click menu still open the SNAG interface.

The extension reads the current URL when its popup is opened, a context-menu action is used, or the YouTube button is clicked. A script runs on www.youtube.com to place the button, but sends no requests until a choice is clicked. It contacts only the local SNAG app. Direct YouTube downloads use its existing desktop download API with a validated quality and the browser-provided video URL. No browser cookies are supplied. It sends no analytics and does not collect cookies. SNAG then contacts the selected video website as usual.

It does not start or install the Windows app automatically. An error badge from a right-click action can be inspected by opening the extension popup. The YouTube script runs in an isolated extension context, ignores synthetic clicks, and the background uses the browser-provided sender URL for that action. It accepts no messages from external website scripts.

## Updating from 1.0

Replace the extracted extension files with this build. On the browser extensions page, click Reload for Send to SNAG and grant YouTube access if requested. Refresh any open YouTube tabs. Start SNAG and open a normal YouTube video to see the button.

This is a development build, not a published store listing. It targets the source interface used by SNAG 1.4. Automated checks cover URL validation and the local-page handoff; actual Chrome/Edge and the supplied exe still need a manual end-to-end check.
