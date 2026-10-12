#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
if [ -z "${DEVELOPER_DIR:-}" ] && [ -d /Applications/Xcode.app/Contents/Developer ]; then
    export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer
fi
swift build -c release --product tick "$@"
binary_dir=$(swift build -c release --show-bin-path "$@")
app="build/Time is Clearly Kept.app"
mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources"
cp Assets/Tick.icns "$app/Contents/Resources/Tick.icns"
cp "$binary_dir/tick" "$app/Contents/MacOS/tick"
cat > "$app/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleIconFile</key><string>Tick</string>
<key>CFBundleExecutable</key><string>tick</string>
<key>CFBundleIdentifier</key><string>org.timeisclearlykept.mac</string>
<key>CFBundleName</key><string>Time is Clearly Kept</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleShortVersionString</key><string>0.1.0</string>
<key>CFBundleVersion</key><string>1</string>
<key>LSMinimumSystemVersion</key><string>14.0</string>
<key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST
printf 'Built %s\n' "$PWD/$app"
