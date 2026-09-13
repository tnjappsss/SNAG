/*
 * SNAG for Android
 * Copyright (C) 2026 TNJAPS
 *
 * This program is free software: you can redistribute it and/or modify it under
 * the terms of the GNU General Public License as published by the Free Software
 * Foundation, either version 3 of the License, or (at your option) any later
 * version. It is distributed WITHOUT ANY WARRANTY; see the GNU General Public
 * License for more details. You should have received a copy of the licence along
 * with this program. If not, see <https://www.gnu.org/licenses/>.
 *
 * Additional permission under GNU GPL version 3 section 7: if you modify this
 * Program, or any covered work, by linking or combining it with the Google Mobile
 * Ads SDK, the Google User Messaging Platform SDK, or Google Play services (or
 * modified versions of those libraries), containing parts covered by terms other
 * than the GNU General Public License, the copyright holder grants you additional
 * permission to convey the resulting work. See docs/LICENSE-EXCEPTION.md.
 */
package com.snag.app

import android.annotation.SuppressLint
import android.content.Intent
import android.os.Bundle
import android.system.Os
import android.util.Log
import android.view.ViewGroup
import android.view.WindowManager
import android.widget.LinearLayout
import android.webkit.JavascriptInterface
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.activity.OnBackPressedCallback
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.FileProvider
import com.google.android.gms.ads.AdRequest
import com.google.android.gms.ads.AdSize
import com.google.android.gms.ads.AdView
import com.google.android.gms.ads.MobileAds
import com.google.android.gms.ads.RequestConfiguration
import com.google.android.ump.ConsentInformation
import com.google.android.ump.ConsentRequestParameters
import com.google.android.ump.UserMessagingPlatform
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import org.json.JSONObject
import java.io.BufferedInputStream
import java.io.File
import java.util.zip.ZipInputStream

class MainActivity : AppCompatActivity() {

    // NOTE: must be lazy. Calling getExternalFilesDir() in a property initialiser
    // runs before the Context is attached and throws NullPointerException.
    private val outdir: File by lazy {
        File(getExternalFilesDir(null), "SNAG").apply { mkdirs() }
    }
    private val ffmpegHome: File by lazy { File(filesDir, "ffmpeg") }

    private lateinit var web: WebView
    private var pendingUrl: String? = null
    private var serverReady = false

    private var adView: AdView? = null
    private var adsStarted = false
    private lateinit var consent: ConsentInformation

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // Downloads die if the process is backgrounded and killed; keeping the
        // screen awake while SNAG is in front is the cheap version of a wakelock.
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)

        // Remote WebView inspection is a debug-only convenience; leaving it on in a
        // release build lets anything with debug access read the page.
        WebView.setWebContentsDebuggingEnabled(BuildConfig.DEBUG)
        web = WebView(this).apply {
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            settings.mediaPlaybackRequiresUserGesture = false
            addJavascriptInterface(ShareBridge(), "Android")
            webViewClient = object : WebViewClient() {
                override fun onPageFinished(view: WebView?, url: String?) {
                    if (serverReady) consumePendingUrl()
                }

                /**
                 * Keep the local UI in the WebView, hand everything else to a browser.
                 *
                 * This WebView has no address bar, back button or tabs, so an outbound
                 * link opened inside it would be a dead end. It would also be blocked
                 * by the loopback-only network security config.
                 */
                override fun shouldOverrideUrlLoading(
                    view: WebView, request: WebResourceRequest
                ): Boolean {
                    val uri = request.url
                    if (uri.host == "127.0.0.1" || uri.host == "localhost") return false
                    return try {
                        startActivity(
                            Intent(Intent.ACTION_VIEW, uri)
                                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                        )
                        true
                    } catch (e: Exception) {
                        Log.w("snag", "nothing can open $uri", e)
                        true
                    }
                }
            }
        }
        // The WebView takes all remaining height and the banner is anchored below
        // it, so an ad never covers the UI.
        val root = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        root.addView(
            web,
            LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f)
        )
        adView = AdView(this).apply {
            adUnitId = BuildConfig.ADMOB_BANNER_ID
            setAdSize(
                AdSize.getCurrentOrientationAnchoredAdaptiveBannerAdSize(
                    this@MainActivity, resources.configuration.screenWidthDp
                )
            )
        }
        root.addView(
            adView,
            LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT
            )
        )
        setContentView(
            root,
            ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT
            )
        )
        gatherConsentThenLoadAds()

        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                if (web.canGoBack()) web.goBack() else finish()
            }
        })

        web.loadDataWithBaseURL(null, SPLASH, "text/html", "utf-8", null)
        pendingUrl = extractSharedUrl(intent)
        startPythonServer()
    }

    /**
     * Ask for consent first, then start the ads SDK.
     *
     * Denmark is in the EEA, so a consent decision is required before any
     * personalised ad request. UMP shows the form when it is needed and does
     * nothing when it is not. If the lookup fails we still check canRequestAds(),
     * which honours any decision already stored on the device.
     */
    private fun gatherConsentThenLoadAds() {
        consent = UserMessagingPlatform.getConsentInformation(this)
        consent.requestConsentInfoUpdate(
            this,
            ConsentRequestParameters.Builder().build(),
            {
                UserMessagingPlatform.loadAndShowConsentFormIfRequired(this) { formError ->
                    if (formError != null) Log.w("snag", "consent form: ${formError.message}")
                    if (consent.canRequestAds()) startAds()
                }
            },
            { requestError ->
                Log.w("snag", "consent lookup: ${requestError.message}")
                if (consent.canRequestAds()) startAds()
            }
        )
    }

    /** Initialise the ads SDK once and request the banner. */
    private fun startAds() {
        if (adsStarted) return
        adsStarted = true

        // Real ad units must never serve live ads to the developer's own phone, or
        // AdMob counts it as invalid traffic. The hashed device ID is printed to
        // logcat by the SDK on first run; put it in local.properties.
        if (BuildConfig.ADMOB_TEST_DEVICE.isNotEmpty()) {
            MobileAds.setRequestConfiguration(
                RequestConfiguration.Builder()
                    .setTestDeviceIds(listOf(BuildConfig.ADMOB_TEST_DEVICE))
                    .build()
            )
        }
        // initialize() does disk and network work, so keep it off the main thread.
        Thread {
            MobileAds.initialize(this) {
                runOnUiThread { adView?.loadAd(AdRequest.Builder().build()) }
            }
        }.start()
    }

    override fun onPause() {
        adView?.pause()
        super.onPause()
    }

    override fun onResume() {
        super.onResume()
        adView?.resume()
    }

    override fun onDestroy() {
        adView?.destroy()
        super.onDestroy()
    }

    /**
     * Unpack the bundled ffmpeg on first launch.
     *
     * ffmpeg is dynamically linked against ~78 shared libraries, so those ride
     * along in assets and are extracted here. The executables live in jniLibs:
     * since Android 10 the native library directory is the only place an app may
     * exec from, so we symlink usable names into it, because yt-dlp looks for
     * files literally named ffmpeg and ffprobe.
     *
     * @return (dir holding the ffmpeg/ffprobe links, dir holding the libraries)
     */
    private fun prepareFfmpeg(): Pair<String, String>? = try {
        val libDir = File(ffmpegHome, "lib")
        val binDir = File(ffmpegHome, "bin")
        val stamp = File(ffmpegHome, ".unpacked-v1")

        if (!stamp.exists()) {
            setSplashNote("unpacking ffmpeg, one moment")
            libDir.deleteRecursively()
            libDir.mkdirs()
            assets.open(FFMPEG_ASSET).use { raw ->
                ZipInputStream(BufferedInputStream(raw)).use { zis ->
                    while (true) {
                        val entry = zis.nextEntry ?: break
                        if (!entry.isDirectory) {
                            File(libDir, File(entry.name).name).outputStream()
                                .use { zis.copyTo(it, 1 shl 16) }
                        }
                        zis.closeEntry()
                    }
                }
            }
            stamp.writeText("ok")
        }

        binDir.mkdirs()
        val nativeDir = applicationInfo.nativeLibraryDir
        for ((name, real) in listOf("ffmpeg" to "libffmpeg.so", "ffprobe" to "libffprobe.so")) {
            val link = File(binDir, name)
            // Always recreate. Every install gives the app a fresh /data/app path,
            // so a link from a previous version dangles - and a dangling link reports
            // exists() == false while still occupying the name, which made symlink()
            // fail with EEXIST and silently cost us ffmpeg after each update.
            link.delete()
            Os.symlink(File(nativeDir, real).absolutePath, link.absolutePath)
        }
        val probe = File(binDir, "ffmpeg")
        check(probe.canExecute()) { "ffmpeg link not executable at ${probe.absolutePath}" }
        binDir.absolutePath to libDir.absolutePath
    } catch (e: Throwable) {
        // Not fatal: without ffmpeg, single-file downloads (TikTok, X) still work.
        Log.e("snag", "ffmpeg setup failed", e)
        null
    }

    /** Boot the interpreter and the snag.py HTTP server off the main thread. */
    private fun startPythonServer() {
        Thread {
            val result = try {
                val ff = prepareFfmpeg()
                setSplashNote("starting python")
                if (!Python.isStarted()) Python.start(AndroidPlatform(this))
                Python.getInstance()
                    .getModule("snag")
                    .callAttr("serve", 0, outdir.absolutePath, ff?.first, ff?.second)
                    .toString()
            } catch (e: Throwable) {
                Log.e("snag", "startup failed", e)
                "ERROR:" + (e.message ?: e.toString())
            }
            runOnUiThread {
                if (result.startsWith("ERROR:")) {
                    web.loadDataWithBaseURL(
                        null, errorPage(result.removePrefix("ERROR:")),
                        "text/html", "utf-8", null
                    )
                } else {
                    serverReady = true
                    web.loadUrl(result)
                }
            }
        }.start()
    }

    private fun setSplashNote(text: String) = runOnUiThread {
        web.evaluateJavascript(
            "var p=document.querySelector('p');if(p)p.textContent=" + JSONObject.quote(text) + ";",
            null
        )
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        pendingUrl = extractSharedUrl(intent)
        if (serverReady) consumePendingUrl()
    }

    /** Pull a URL out of a "Share to SNAG" intent. */
    private fun extractSharedUrl(intent: Intent?): String? {
        if (intent?.action != Intent.ACTION_SEND) return null
        val text = intent.getStringExtra(Intent.EXTRA_TEXT) ?: return null
        return Regex("""https?://\S+""").find(text)?.value
    }

    /** Drop a shared link into the URL box on the page and press Grab. */
    private fun consumePendingUrl() {
        val url = pendingUrl ?: return
        pendingUrl = null
        val quoted = JSONObject.quote(url)
        web.evaluateJavascript(
            """(function(){
                 var i=document.querySelector('#url'), b=document.querySelector('#goBtn');
                 if(!i||!b) return;
                 i.value=$quoted;
                 i.dispatchEvent(new Event('input',{bubbles:true}));
                 b.click();
               })();""".trimIndent(), null
        )
    }

    inner class ShareBridge {
        @JavascriptInterface
        fun share(name: String) {
            val f = File(outdir, File(name).name)
            if (!f.exists()) return
            val uri = FileProvider.getUriForFile(
                this@MainActivity, "$packageName.fileprovider", f
            )
            val mime = when (f.extension.lowercase()) {
                "mp3" -> "audio/mpeg"
                "webm" -> "video/webm"
                "mkv" -> "video/x-matroska"
                "mov" -> "video/quicktime"
                else -> "video/mp4"
            }
            val send = Intent(Intent.ACTION_SEND).apply {
                type = mime
                putExtra(Intent.EXTRA_STREAM, uri)
                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            }
            runOnUiThread {
                startActivity(Intent.createChooser(send, "Save / share download"))
            }
        }
    }

    private fun errorPage(msg: String) = """
        <!doctype html><meta name="viewport" content="width=device-width,initial-scale=1">
        <body style="background:#F4F2EC;color:#15181D;font-family:system-ui;padding:2rem">
        <h2 style="color:#FF0033">SNAG could not start</h2>
        <pre style="white-space:pre-wrap;font-size:13px;background:#fff;border:2px solid #15181D;
             border-radius:10px;padding:1rem">${msg.replace("<", "&lt;")}</pre></body>
    """.trimIndent()

    companion object {
        private const val FFMPEG_ASSET = "ffmpeg-arm64-v8a.zip"

        private val SPLASH = """
            <!doctype html><meta name="viewport" content="width=device-width,initial-scale=1">
            <style>
              body{background:#F4F2EC;color:#15181D;font-family:system-ui;display:flex;
                   height:100vh;margin:0;align-items:center;justify-content:center;
                   flex-direction:column;gap:1rem}
              @media (prefers-color-scheme:dark){body{background:#15181D;color:#F4F2EC}}
              .eq{display:flex;gap:4px;align-items:flex-end;height:34px}
              .eq i{width:7px;border-radius:1px;animation:eq 1s ease-in-out infinite}
              .eq i:nth-child(1){background:#FF0033}
              .eq i:nth-child(2){background:currentColor;animation-delay:.18s}
              .eq i:nth-child(3){background:#0db6b2;animation-delay:.36s}
              .eq i:nth-child(4){background:#FE2C55;animation-delay:.54s}
              @keyframes eq{0%,100%{height:8px}50%{height:32px}}
              p{font:500 11px ui-monospace,monospace;letter-spacing:.2em;opacity:.55;
                text-transform:uppercase}
            </style>
            <div class="eq"><i></i><i></i><i></i><i></i></div>
            <p>starting python</p>
        """.trimIndent()
    }
}
