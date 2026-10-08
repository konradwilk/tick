// Run from the repository root: swift apple/scripts/generate-icons.swift
import AppKit

let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
let assets = root.appendingPathComponent("Assets")
guard let artwork = NSImage(contentsOf: assets.appendingPathComponent("folder-clock.svg")) else {
    fatalError("Cannot load folder-clock.svg")
}
func render(size: Int, rounded: Bool, to file: URL) throws {
    let bitmap = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: size, pixelsHigh: size,
        bitsPerSample: 8, samplesPerPixel: rounded ? 4 : 3, hasAlpha: rounded, isPlanar: false,
        colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: bitmap)
    let side = CGFloat(size)
    let inset = rounded ? side * 0.05 : 0
    NSColor.white.setFill()
    let background = NSRect(x: inset, y: inset, width: side - inset * 2, height: side - inset * 2)
    NSBezierPath(roundedRect: background, xRadius: rounded ? side * 0.2 : 0,
        yRadius: rounded ? side * 0.2 : 0).fill()
    artwork.draw(in: NSRect(x: side * 0.125, y: side * 0.125, width: side * 0.75, height: side * 0.75),
        from: .zero, operation: .sourceOver, fraction: 1)
    NSGraphicsContext.restoreGraphicsState()
    try bitmap.representation(using: .png, properties: [:])!.write(to: file)
}
let iconset = root.appendingPathComponent("build/Tick.iconset")
try FileManager.default.createDirectory(at: iconset, withIntermediateDirectories: true)
for size in [16, 32, 128, 256, 512] {
    try render(size: size, rounded: true, to: iconset.appendingPathComponent("icon_\(size)x\(size).png"))
    try render(size: size * 2, rounded: true, to: iconset.appendingPathComponent("icon_\(size)x\(size)@2x.png"))
}
let process = Process()
process.executableURL = URL(fileURLWithPath: "/usr/bin/iconutil")
process.arguments = ["-c", "icns", iconset.path, "-o", assets.appendingPathComponent("Tick.icns").path]
try process.run()
process.waitUntilExit()
guard process.terminationStatus == 0 else { fatalError("iconutil failed") }
try render(size: 1024, rounded: false,
    to: root.appendingPathComponent("iOS/Assets.xcassets/AppIcon.appiconset/AppIcon.png"))
