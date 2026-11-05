#!/usr/bin/env bash
set -euo pipefail

app=$(cd "$(dirname "$0")" && pwd)
sdk=${ANDROID_HOME:-${ANDROID_SDK_ROOT:-}}
[[ -n "$sdk" ]] || { echo 'Set ANDROID_HOME to the Android SDK directory.' >&2; exit 1; }
tools="$sdk/build-tools/35.0.0"
platform="$sdk/platforms/android-35/android.jar"
out=${1:-"$app/out"}
mkdir -p "$out"
out=$(cd "$out" && pwd)
work=$(mktemp -d "$out/work.XXXXXX")
mkdir -p "$work/res/drawable-nodpi" "$work/generated" "$work/classes" "$work/dex" "$work/test"

javac --release 8 -d "$work/test" \
  "$app/src/io/meuagent/preview/MeuEndpoint.java" "$app/test/MeuEndpointTest.java"
java -cp "$work/test" io.meuagent.preview.MeuEndpointTest

cp "$app/../desktop/assets/meu-icon.png" "$work/res/drawable-nodpi/meu_icon.png"
"$tools/aapt2" compile --dir "$work/res" -o "$work/resources.zip"
"$tools/aapt2" link -I "$platform" --manifest "$app/AndroidManifest.xml" \
  --java "$work/generated" -o "$work/resources.apk" "$work/resources.zip"
mapfile -t sources < <(find "$app/src" "$work/generated" -name '*.java' | sort)
javac --release 8 -encoding UTF-8 -classpath "$platform" -d "$work/classes" "${sources[@]}"
jar cf "$work/classes.jar" -C "$work/classes" .
"$tools/d8" --min-api 26 --lib "$platform" --output "$work/dex" "$work/classes.jar"
jar uf "$work/resources.apk" -C "$work/dex" classes.dex
"$tools/zipalign" -f 4 "$work/resources.apk" "$work/aligned.apk"

# A fresh key per preview build. This package is separate from any future production app.
keytool -genkeypair -noprompt -keystore "$work/preview.jks" -storepass android \
  -keypass android -alias meu-preview -keyalg RSA -keysize 2048 -validity 365 \
  -dname 'CN=Meu Android Preview'
"$tools/apksigner" sign --ks "$work/preview.jks" --ks-pass pass:android \
  --out "$out/Meu-Android-preview.apk" "$work/aligned.apk"
"$tools/apksigner" verify --print-certs "$out/Meu-Android-preview.apk"
(cd "$out" && sha256sum Meu-Android-preview.apk > SHA256SUMS.txt)
