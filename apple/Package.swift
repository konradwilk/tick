// swift-tools-version: 6.0
import PackageDescription
let package = Package(
    name: "tick",
    platforms: [.macOS(.v14), .iOS(.v17)],
    products: [.library(name: "HoursCore", targets: ["HoursCore"]), .executable(name: "tick", targets: ["HoursMac"])],
    targets: [
        .target(name: "HoursCore", plugins: [.plugin(name: "BuildVersionPlugin")]),
        .executableTarget(name: "HoursMac", dependencies: ["HoursCore"]),
        .testTarget(name: "HoursCoreTests", dependencies: ["HoursCore"]),
        .plugin(name: "BuildVersionPlugin", capability: .buildTool())
    ]
)
