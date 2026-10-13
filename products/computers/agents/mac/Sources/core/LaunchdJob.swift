import Foundation

/// One launchd job the beacon installs, as the Prefs page's Services card shows it.
/// Read-only: what launchd reports and what the job's plist asks for, never an action.
public struct LaunchdJob: Identifiable, Equatable, Sendable {
    public var id: String { label }
    public let label: String
    public let title: String
    public var state: String
    public var pid: Int?
    public var lastExitCode: String?
    public var schedule: String
    public var program: String?

    /// The jobs the package installs: the agent, and the helper the app registers.
    public static let installed: [(label: String, title: String, plist: String)] = [
        (PulseConstants.agentLabel, "Agent", "/Library/LaunchDaemons/\(PulseConstants.agentLabel).plist"),
        (PulseConstants.helperLabel, "Privileged helper",
         PulseConstants.appPath + "/Contents/Library/LaunchDaemons/\(PulseConstants.helperPlistName)"),
    ]

    /// Every installed job's current status. `launchctl print` reads the system domain
    /// without privileges.
    public static func readAll() -> [LaunchdJob] {
        installed.map { job in
            let plist = NSDictionary(contentsOfFile: job.plist) as? [String: Any]
            let printed = launchctlPrint("system/\(job.label)")
            return make(label: job.label, title: job.title, plist: plist, printed: printed)
        }
    }

    static func make(label: String, title: String, plist: [String: Any]?, printed: String?) -> LaunchdJob {
        let fields = printed.map(parsePrint) ?? [:]
        let state: String
        if let s = fields["state"] {
            state = s.prefix(1).uppercased() + s.dropFirst()
        } else {
            state = plist == nil ? "Not installed" : "Not loaded"
        }
        let exit = fields["last exit code"].map { $0 == "(never exited)" ? "Never exited" : $0 }
        return LaunchdJob(label: label, title: title, state: state,
                          pid: fields["pid"].flatMap(Int.init), lastExitCode: exit,
                          schedule: schedule(plist), program: program(plist))
    }

    /// The top-level `key = value` lines of `launchctl print`; nested blocks are skipped.
    static func parsePrint(_ text: String) -> [String: String] {
        var out: [String: String] = [:]
        for line in text.components(separatedBy: .newlines) {
            guard line.hasPrefix("\t"), !line.hasPrefix("\t\t") else { continue }
            let parts = line.dropFirst().components(separatedBy: " = ")
            guard parts.count >= 2 else { continue }
            let key = parts[0].trimmingCharacters(in: .whitespaces)
            if out[key] == nil { out[key] = parts.dropFirst().joined(separator: " = ").trimmingCharacters(in: .whitespaces) }
        }
        return out
    }

    static func schedule(_ plist: [String: Any]?) -> String {
        guard let plist else { return "—" }
        if let seconds = plist["StartInterval"] as? Int { return "Every \(seconds) seconds" }
        if plist["StartCalendarInterval"] != nil { return "On a calendar schedule" }
        if let keepAlive = plist["KeepAlive"] as? Bool, keepAlive { return "Always running, restarted if it exits" }
        if plist["KeepAlive"] is [String: Any] { return "Kept running while its conditions hold" }
        if plist["MachServices"] != nil { return "On demand, when the app connects" }
        if plist["RunAtLoad"] as? Bool == true { return "Once at startup" }
        return "On demand"
    }

    static func program(_ plist: [String: Any]?) -> String? {
        if let args = plist?["ProgramArguments"] as? [String], !args.isEmpty { return args.joined(separator: " ") }
        if let program = plist?["Program"] as? String { return program }
        if let bundled = plist?["BundleProgram"] as? String { return PulseConstants.appPath + "/" + bundled }
        return nil
    }

    private static func launchctlPrint(_ target: String) -> String? {
        let task = Process()
        task.executableURL = URL(fileURLWithPath: "/bin/launchctl")
        task.arguments = ["print", target]
        let pipe = Pipe()
        task.standardOutput = pipe
        task.standardError = FileHandle.nullDevice
        do { try task.run() } catch { return nil }
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        task.waitUntilExit()
        return task.terminationStatus == 0 ? String(decoding: data, as: UTF8.self) : nil
    }
}
