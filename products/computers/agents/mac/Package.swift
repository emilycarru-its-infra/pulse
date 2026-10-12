// swift-tools-version:6.0
import PackageDescription

let package = Package(
    name: "ManagedPresenceBeacon",
    platforms: [
        .macOS(.v14)
    ],
    products: [
        .executable(name: "managedpresencebeacon", targets: ["PulseAgentCLI"]),
        .executable(name: "ManagedPresenceBeaconApp", targets: ["PulseAgentApp"]),
        .executable(name: "ManagedPresenceBeaconHelper", targets: ["PulseAgentHelper"]),
        .library(name: "PulseAgentCore", targets: ["PulseAgentCore"])
    ],
    targets: [
        .target(name: "PulseAgentCore", path: "Sources/core"),
        .executableTarget(name: "PulseAgentCLI", dependencies: ["PulseAgentCore"], path: "Sources/cli"),
        .executableTarget(name: "PulseAgentApp", dependencies: ["PulseAgentCore"], path: "Sources/app"),
        .executableTarget(name: "PulseAgentHelper", dependencies: ["PulseAgentCore"], path: "Sources/helper"),
        .testTarget(name: "PulseAgentCoreTests", dependencies: ["PulseAgentCore"], path: "Tests/PulseAgentCoreTests")
    ]
)
