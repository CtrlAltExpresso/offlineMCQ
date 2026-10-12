# LiveMCQ Offline (Android)

Sideloadable Android app that bundles the recovered LiveMCQ viewer/site for
fully-offline use on a phone or tablet.

The app itself is tiny (~33 KB). The ~9 GB content is delivered as a chunked,
SHA-256-verified bundle that the app downloads and installs itself on first
launch — no manual file placement, no OBB, no second app.

Why this design: a single >4 GB APK is impossible. Android's APK reader
(`libziparchive`), Google's `zipalign`/`apksig` and the Play Store all lack
zip64 support, and PDF files alone in the content are 4.8 GB — so the content
can never fit in one APK.

## Contents of this directory

- `AndroidManifest.xml`, `res/` — app manifest and resources.
- `src/io/livemcq/offline/` — plain-Java app, no AndroidX/Gradle:
- `MainActivity.java` — setup screen (URL field + live progress), then a WebView.
- `DownloadService.java` — foreground service that owns the sync so the download
  keeps running when the app is backgrounded or the screen is off. Puts a live
  progress notification in the tray and relays progress to the activity.
- `ContentManager.java` — downloads the manifest + 21 `.zip` parts with HTTP
  Range resume into internal storage, verifies each part's SHA-256 and
  extracts it. Reports real-time cumulative bytes (updated ~every 0.4 s) so the
  progress bar/percent move continuously instead of per-part. Completed parts
  are marked on disk (`.ok` files, each recording that part's SHA-256), so a
  paused/interrupted download resumes
  exactly where it stopped — already-done parts are skipped and the progress
  continues from the saved byte count, never from 0. Safe against interrupted
  downloads and non-Range servers (a `200` full-body reply is caught by the
  SHA check and re-done).
- `AssetServer.java` — minimal HTTP server on `127.0.0.1` that streams the
  extracted tree to the WebView. Paths map 1:1 (disk filenames are their
  literal percent-escaped forms, which browsers send verbatim); traversal and
  missing files return 404.
- `Config.java` — commit-time default manifest URL (empty unless baked).
- `build_apk.sh` — build pipeline (javac → d8 → aapt2 → zipalign → apksigner).

## What the user does

1. Install `offlineMCQ.apk` (built below) and open it (a notification
   permission prompt appears on Android 13+ — allow it so the tray shows
   download progress).
2. Paste the manifest URL (`https://…/livemcq_manifest.json`) into the field.
3. Tap **Start download** (~9 GB; live progress bar + percentage). If you're on
   mobile data, a warning dialog asks you to confirm before starting. The download
   runs in a foreground service, so you can background the app or turn the
   screen off and it keeps going — watch the notification. It resumes where it
   stopped if interrupted. Once finished the viewer opens and everything works
   offline.

## Installing: the Play Protect warning is expected

Sideloading any new APK triggers Google Play Protect's "App blocked to protect
your device — Play Protect hasn't seen an app from this developer before."
This is normal for a freshly-signed app, not a sign of a problem. The APK is
~33 KB, requests only INTERNET / network-state / notification / wake-lock /
foreground-service permissions, and is signed with the same keystore for every
build (checksum is identical between rebuilds).

To get past it:

1. On the "App blocked" screen tap **More details**.
2. Tap **Install anyway**.
3. If prompted again, tap **Install anyway** one more time.

To silence the warning permanently, submit the APK for a Play Protect scan
review (Google Play Console → Play Protect status → request a scan review, or
the support form at `https://support.google.com/googleplay/android-developer`).
After approval the warning stops for every install signed with this keystore.

## Build prerequisites

- Android SDK with `build-tools;34.0.0`, `platforms;android-34` (used from
  `$ANDROID_SDK_ROOT`, default `/home/sakib/android-sdk`).
- A JDK 17+ for `javac`/`keytool` (compiled with `--release 8` — D8 8.2.x
  crashes with an internal NPE on anonymous-inner-class bytecode emitted by
  newer JDKs; source/target 8 is also why the app has no modern-Java syntax).

## Build

```sh
# plain (user pastes the manifest URL on first run)
bash android/build_apk.sh                       # -> dist/LiveMCQ_Offline.apk

# URL baked in, no typing needed (this repo's published bundle):
SOURCE_URL=https://github.com/CtrlAltExpresso/offlineMCQ/releases/download/content-v2/livemcq_manifest.json \
  bash android/build_apk.sh
```

On first run the script also generates `dist/livemcq.keystore` (reused on later
builds, so updates install over old versions). Keep that keystore — it is the
only way to sign future updates of this app.

## Producing and hosting the content bundle

For the user flow to work, the ~9 GB bundle must be uploaded somewhere with
direct HTTPS file URLs that support HTTP Range (archive.org works; so does any
VPS with nginx/rsync). Also note: publishing the content publicly re-distributes
copyrighted LiveMCQ material — you are responsible for the hosting choice.

```sh
python3 scripts/make_content_bundle.py /home/sakib/android_apk_build/bundle
```

produces `bundle/part_0000.zip … part_0020.zip` (21 parts) + `bundle/livemcq_manifest.json`
(manifest lists each part's file, size and sha256). Upload the whole directory
so the manifest and parts sit side by side. archive.org example:

```sh
ia upload your-item bundle/* --metadata="title=LiveMCQ Offline Bundle" \
  --metadata="mediatype=data" --metadata="collection=opensource"
```

The manifest URL is then
`https://archive.org/download/your-item/livemcq_manifest.json`. Every part is
locally verified end-to-end: SHA-256 checksums match the manifest and a full
extract of all 21 parts is byte-identical to the source tree.