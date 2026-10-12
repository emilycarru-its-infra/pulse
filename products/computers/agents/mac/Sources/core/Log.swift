import Foundation

/// The agent's log, one line per entry, in /Library/Managed Pulse/logs. Lines read
/// `[2026-10-12 14:03:22] INFO  message`, the layout the suite's log views colour.
public final class PulseLog: @unchecked Sendable {
    public enum Level: String, Sendable { case debug = "DEBUG", info = "INFO ", warn = "WARN ", error = "ERROR" }

    public static let shared = PulseLog()

    public var path = PulseConstants.logPath
    public var verbose = false
    /// Also print each line, for the CLI run by hand or by the app's Send now.
    public var echo = false
    private let queue = DispatchQueue(label: "managedpulse.log")
    private let maxBytes: UInt64 = 5 * 1024 * 1024

    public func debug(_ m: String) { write(.debug, m) }
    public func info(_ m: String) { write(.info, m) }
    public func warn(_ m: String) { write(.warn, m) }
    public func error(_ m: String) { write(.error, m) }

    private func write(_ level: Level, _ message: String) {
        if level == .debug && !verbose { return }
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd HH:mm:ss"
        f.locale = Locale(identifier: "en_US_POSIX")
        let line = "[\(f.string(from: Date()))] \(level.rawValue) \(message)\n"
        if echo { FileHandle.standardOutput.write(Data(line.utf8)) }
        queue.sync {
            let fm = FileManager.default
            let dir = (path as NSString).deletingLastPathComponent
            guard fm.isWritableFile(atPath: dir) || ((try? fm.createDirectory(atPath: dir, withIntermediateDirectories: true)) != nil) else { return }
            if let size = (try? fm.attributesOfItem(atPath: path))?[.size] as? UInt64, size > maxBytes {
                try? fm.removeItem(atPath: path + ".1")
                try? fm.moveItem(atPath: path, toPath: path + ".1")
            }
            if let handle = FileHandle(forWritingAtPath: path) {
                handle.seekToEndOfFile()
                handle.write(Data(line.utf8))
                try? handle.close()
            } else {
                fm.createFile(atPath: path, contents: Data(line.utf8), attributes: [.posixPermissions: 0o644])
            }
        }
    }
}
