#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
if [ -z "${DEVELOPER_DIR:-}" ] && [ -d /Applications/Xcode.app/Contents/Developer ]; then
    export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer
fi
swift build -c release --product NonprofitHours "$@"
binary_dir=$(swift build -c release --show-bin-path "$@")
app="build/Nonprofit Hours.app"
mkdir -p "$app/Contents/MacOS"
cp "$binary_dir/NonprofitHours" "$app/Contents/MacOS/NonprofitHours"
cat > "$app/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleExecutable</key><string>NonprofitHours</string>
<key>CFBundleIdentifier</key><string>org.nonprofithours.mac</string>
<key>CFBundleName</key><string>Nonprofit Hours</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleShortVersionString</key><string>0.1.0</string>
<key>CFBundleVersion</key><string>1</string>
<key>LSMinimumSystemVersion</key><string>14.0</string>
<key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST
printf 'Built %s\n' "$PWD/$app"
