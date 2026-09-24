// swift-tools-version: 6.0
import PackageDescription
let package = Package(
    name: "NonprofitHours",
    platforms: [.macOS(.v14), .iOS(.v17)],
    products: [.library(name: "HoursCore", targets: ["HoursCore"]), .executable(name: "NonprofitHours", targets: ["HoursMac"])],
    targets: [.target(name: "HoursCore"), .executableTarget(name: "HoursMac", dependencies: ["HoursCore"]), .testTarget(name: "HoursCoreTests", dependencies: ["HoursCore"])]
)
