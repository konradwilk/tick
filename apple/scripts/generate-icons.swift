// Run from the repository root: swift apple/scripts/generate-icons.swift
import AppKit

let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
let assets = root.appendingPathComponent("Assets")
// Render the folder-clock vector directly into a bitmap context. Avoid drawing
// an SVG NSImage through an offscreen NSGraphicsContext, which can produce an
// empty (black) RGB bitmap on some systems.
func render(size: Int, rounded: Bool, to file: URL) throws {
    let side = CGFloat(size)
    guard let context = CGContext(data: nil, width: size, height: size,
        bitsPerComponent: 8, bytesPerRow: 0,
        space: CGColorSpace(name: CGColorSpace.sRGB)!,
        bitmapInfo: (rounded ? CGImageAlphaInfo.premultipliedLast : CGImageAlphaInfo.noneSkipLast).rawValue)
    else { fatalError("Cannot create icon bitmap") }
    let inset = rounded ? side * 0.05 : 0
    let background = CGRect(x: inset, y: inset, width: side - inset * 2, height: side - inset * 2)
    context.setFillColor(CGColor(gray: 1, alpha: 1))
    context.addPath(CGPath(roundedRect: background,
        cornerWidth: rounded ? side * 0.2 : 0, cornerHeight: rounded ? side * 0.2 : 0, transform: nil))
    context.fillPath()
    // SVG coordinates: 24 x 24, with a 12.5% margin and downward y axis.
    context.translateBy(x: side * 0.125, y: side * 0.875)
    context.scaleBy(x: side * 0.75 / 24, y: -side * 0.75 / 24)
    context.setStrokeColor(CGColor(gray: 0, alpha: 1))
    context.setLineWidth(2)
    context.setLineCap(.round)
    context.setLineJoin(.round)
    context.move(to: CGPoint(x: 16, y: 14))
    context.addLine(to: CGPoint(x: 16, y: 16.2))
    context.addLine(to: CGPoint(x: 17.6, y: 17.2))
    context.strokePath()
    context.move(to: CGPoint(x: 7, y: 20))
    context.addLine(to: CGPoint(x: 4, y: 20))
    context.addCurve(to: CGPoint(x: 2, y: 18), control1: CGPoint(x: 2.8954, y: 20), control2: CGPoint(x: 2, y: 19.1046))
    context.addLine(to: CGPoint(x: 2, y: 5))
    context.addCurve(to: CGPoint(x: 4, y: 3), control1: CGPoint(x: 2, y: 3.8954), control2: CGPoint(x: 2.8954, y: 3))
    context.addLine(to: CGPoint(x: 7.9, y: 3))
    context.addCurve(to: CGPoint(x: 9.59, y: 3.9), control1: CGPoint(x: 8.58, y: 3), control2: CGPoint(x: 9.22, y: 3.34))
    context.addLine(to: CGPoint(x: 10.4, y: 5.1))
    context.addCurve(to: CGPoint(x: 12.07, y: 6), control1: CGPoint(x: 10.77, y: 5.66), control2: CGPoint(x: 11.39, y: 6))
    context.addLine(to: CGPoint(x: 20, y: 6))
    context.addCurve(to: CGPoint(x: 22, y: 8), control1: CGPoint(x: 21.1046, y: 6), control2: CGPoint(x: 22, y: 6.8954))
    context.strokePath()
    context.strokeEllipse(in: CGRect(x: 10, y: 10, width: 12, height: 12))
    guard let image = context.makeImage() else { fatalError("Cannot render icon") }
    let bitmap = NSBitmapImageRep(cgImage: image)
    guard let png = bitmap.representation(using: .png, properties: [:]) else { fatalError("Cannot encode icon") }
    try png.write(to: file)
}
try render(size: 1024, rounded: false,
    to: root.appendingPathComponent("iOS/Assets.xcassets/AppIcon.appiconset/AppIcon.png"))
if CommandLine.arguments.contains("--ios-only") { exit(0) }
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
