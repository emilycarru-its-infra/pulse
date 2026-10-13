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
    /// The fields ReportMate's System module collects for a launchd job, read from
    /// `launchctl print` and the job's plist.
    public var kind: String = "LaunchDaemon"
    public var arguments: [String] = []
    public var runAtLoad: Bool = false
    public var keepAlive: String = "No"
    public var startInterval: Int?
    public var user: String = "root"
    public var standardOutPath: String?
    public var standardErrorPath: String?
    public var plistPath: String = ""
    /// False when the job's plist is not on disk, so nothing about it can be read.
    public var isInstalled = true

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
            var made = make(label: job.label, title: job.title, plist: plist, printed: printed)
            made.plistPath = job.plist
            if job.label == PulseConstants.helperLabel { made.kind = "Privileged helper (SMAppService)" }
            return made
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
        var job = LaunchdJob(label: label, title: title, state: state,
                             pid: fields["pid"].flatMap(Int.init), lastExitCode: exit,
                             schedule: schedule(plist), program: program(plist))
        if plist?["MachServices"] != nil, plist?["BundleProgram"] != nil { job.kind = "Privileged helper (SMAppService)" }
        job.isInstalled = plist != nil
        job.arguments = Array((plist?["ProgramArguments"] as? [String] ?? []).dropFirst())
        job.runAtLoad = plist?["RunAtLoad"] as? Bool ?? false
        job.keepAlive = keepAliveWords(plist?["KeepAlive"])
        job.startInterval = plist?["StartInterval"] as? Int
        job.user = plist?["UserName"] as? String ?? "root"
        job.standardOutPath = plist?["StandardOutPath"] as? String
        job.standardErrorPath = plist?["StandardErrorPath"] as? String
        return job
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

    /// What the collapsed row shows on the right: "Running (PID n)", "Loaded, not
    /// running" or "Not loaded".
    public var statusText: String {
        if let pid { return "Running (PID \(pid))" }
        if state == "Running" { return "Running" }
        if state == "Not loaded" || state == "Not installed" { return "Not loaded" }
        return "Loaded, not running"
    }

    /// The collapsed row's one secondary line, e.g. "Launch daemon · At startup, kept
    /// running · Last exit 0".
    public var summary: String {
        var when: String
        if let startInterval { when = "Every \(startInterval) seconds" }
        else if keepAlive.hasPrefix("Yes") { when = runAtLoad ? "At startup, kept running" : "Kept running" }
        else if kind.hasPrefix("Privileged helper") { when = "On demand" }
        else { when = runAtLoad ? "At startup" : "On demand" }
        let type = kind.hasPrefix("Privileged helper") ? "Privileged helper" : "Launch daemon"
        guard isInstalled else { return "\(type) · Not installed" }
        var parts = [type, when]
        if let lastExitCode { parts.append(Int(lastExitCode) != nil ? "Last exit \(lastExitCode)" : lastExitCode) }
        return parts.joined(separator: " · ")
    }

    static func keepAliveWords(_ value: Any?) -> String {
        if let on = value as? Bool { return on ? "Yes, restarted whenever it exits" : "No" }
        if let conditions = value as? [String: Any] {
            return "While " + conditions.keys.sorted().joined(separator: ", ")
        }
        return "No"
    }

    static func program(_ plist: [String: Any]?) -> String? {
        if let args = plist?["ProgramArguments"] as? [String], let first = args.first { return first }
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
