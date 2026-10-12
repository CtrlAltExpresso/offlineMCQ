#!/usr/bin/env bash
# Build the offline LiveMCQ Android app (auto-download edition) into one small
# sideloadable APK.
#
# The APK is just the shell: on first launch it downloads the content parts
# from $SOURCE_URL / pasted in-app. Content itself is packaged separately by
# scripts/make_content_bundle.py and uploaded to any HTTPS host.
#
#   SOURCE_URL=https://host.example/livemcq/livemcq_manifest.json ./android/build_apk.sh
#
# Requires: JDK 17+, Android SDK build-tools 34.0.0 + platform android-34.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
SDK="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-/home/sakib/android-sdk}}"
BT="$SDK/build-tools/34.0.0"
PLAT="$SDK/platforms/android-34/android.jar"
OUT="$REPO/dist"
OUTAPK="$OUT/LiveMCQ_Offline.apk"
KEYSTORE="$OUT/livemcq.keystore"
ALIGNED="$OUT/aligned.apk"
SOURCE_URL="${SOURCE_URL:-}"
# Bump these whenever the wrapper (Java/res) changes so a sideloaded update
# installs over the previous one instead of being rejected as a downgrade.
VERSION_CODE="${VERSION_CODE:-5}"
VERSION_NAME="${VERSION_NAME:-1.4}"

mkdir -p "$OUT"

# ---- generate Config.java (ignores the committed fallback) ----
GEN="$OUT/gen/io/livemcq/offline"
mkdir -p "$GEN"
cat > "$GEN/Config.java" <<EOF
package io.livemcq.offline;

public final class Config {
    public static final String DEFAULT_MANIFEST_URL = "$SOURCE_URL";
}
EOF

echo "== compile =="
rm -rf "$OUT/classes" && mkdir -p "$OUT/classes"
SRCS=()
while IFS= read -r f; do SRCS+=("$f"); done < <(
  find "$REPO/android/src" -name '*.java' ! -name 'Config.java'; echo "$GEN/Config.java"
)
javac --release 8 -classpath "$PLAT" -d "$OUT/classes" "${SRCS[@]}"

echo "== dex =="
"$BT/d8" --release --min-api 24 --lib "$PLAT" --output "$OUT" \
  $(find "$OUT/classes" -name '*.class')

echo "== resources/manifest =="
"$BT/aapt2" compile --dir "$REPO/android/res" -o "$OUT/res.zip"
"$BT/aapt2" link -o "$OUT/base.apk" -I "$PLAT" \
  --manifest "$REPO/android/AndroidManifest.xml" \
  --min-sdk-version 24 --target-sdk-version 34 \
  --version-code "$VERSION_CODE" --version-name "$VERSION_NAME" \
  "$OUT/res.zip"

echo "== add dex =="
( cd "$OUT" && zip -q -X "$OUT/base.apk" classes.dex )

echo "== align =="
rm -f "$ALIGNED"
"$BT/zipalign" -f -p 4 "$OUT/base.apk" "$ALIGNED"

echo "== sign =="
if [ ! -f "$KEYSTORE" ]; then
  keytool -genkeypair -keystore "$KEYSTORE" -alias livemcq \
    -keyalg RSA -keysize 2048 -validity 10000 \
    -storepass livemcq -keypass livemcq \
    -dname "CN=LiveMCQ Recovery, O=Recovery, C=BD" 2>/dev/null
fi
rm -f "$OUTAPK"
"$BT/apksigner" sign --ks "$KEYSTORE" --ks-pass pass:livemcq --key-pass pass:livemcq \
  --out "$OUTAPK" "$ALIGNED"

echo "== verify =="
"$BT/apksigner" verify --print-certs "$OUTAPK" | head -3
"$BT/aapt2" dump badging "$OUTAPK" | head -4
echo "APK: $OUTAPK  ($(du -h "$OUTAPK" | cut -f1))"