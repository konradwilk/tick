import PackagePlugin
import Foundation

@main struct BuildVersionPlugin: BuildToolPlugin {
    func createBuildCommands(context: PluginContext, target: Target) throws -> [Command] {
        let script = context.package.directoryURL.deletingLastPathComponent()
            .appendingPathComponent("linux/tick/version.py")
        let output = context.pluginWorkDirectoryURL.appendingPathComponent("Generated")
        let googleOutput = context.pluginWorkDirectoryURL.appendingPathComponent("GoogleConfiguration")
        let configure = context.package.directoryURL.deletingLastPathComponent().appendingPathComponent("tools/configure_google.py")
        return [.prebuildCommand(
            displayName: "Prepare Google installed-app configuration",
            executable: URL(fileURLWithPath: "/usr/bin/env"),
            arguments: ["python3", configure.path, "--format", "swift", "--allow-unconfigured", "--output", googleOutput.appendingPathComponent("GoogleDesktopClient.swift").path],
            outputFilesDirectory: googleOutput), .prebuildCommand(
            displayName: "Derive version from release tag and Git state",
            executable: URL(fileURLWithPath: "/usr/bin/env"),
            arguments: ["python3", script.path, "--format", "swift", "--output",
                        output.appendingPathComponent("BuildVersion.swift").path],
            outputFilesDirectory: output)]
    }
}
