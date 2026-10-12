import Foundation
import IOKit
import SystemConfiguration

/// What the agent sees at the console. It never records who is signed in, only whether
/// someone is.
public struct SessionSnapshot: Equatable, Sendable {
    public var active: Bool
    public var locked: Bool
    public var idleSeconds: Int

    public init(active: Bool, locked: Bool, idleSeconds: Int) {
        self.active = active
        self.locked = locked
        self.idleSeconds = idleSeconds
    }

    /// The seat state the server would show for this snapshot, for the app's Run tab.
    /// Mirrors pulse_core.state: locked or idle 15 minutes reads as possibly free.
    public var seatState: String {
        guard active else { return "available" }
        return locked || idleSeconds >= 900 ? "possibly_free" : "in_use"
    }
}

public enum SessionReader {
    public static func snapshot() -> SessionSnapshot {
        let active = consoleUserPresent()
        return SessionSnapshot(active: active, locked: active && screenLocked(), idleSeconds: idleSeconds())
    }

    /// True when a user, not the login window, owns the console.
    public static func consoleUserPresent() -> Bool {
        guard let store = SCDynamicStoreCreate(nil, "managedpulse" as CFString, nil, nil) else { return false }
        var uid: uid_t = 0
        guard let name = SCDynamicStoreCopyConsoleUser(store, &uid, nil) as String? else { return false }
        return !name.isEmpty && name != "loginwindow" && uid != 0
    }

    /// The console session's lock flag from IOConsoleUsers in the I/O Registry root.
    public static func screenLocked() -> Bool {
        let root = IORegistryGetRootEntry(kIOMainPortDefault)
        defer { IOObjectRelease(root) }
        guard let users = IORegistryEntryCreateCFProperty(root, "IOConsoleUsers" as CFString, kCFAllocatorDefault, 0)?
            .takeRetainedValue() as? [[String: Any]] else { return false }
        let console = users.first { ($0["kCGSSessionOnConsoleKey"] as? Bool) == true } ?? users.first
        return (console?["CGSSessionScreenIsLocked"] as? Bool) ?? false
    }

    /// Seconds since the last keyboard or mouse input, from IOHIDSystem.
    public static func idleSeconds() -> Int {
        let service = IOServiceGetMatchingService(kIOMainPortDefault, IOServiceMatching("IOHIDSystem"))
        guard service != 0 else { return 0 }
        defer { IOObjectRelease(service) }
        guard let value = IORegistryEntryCreateCFProperty(service, "HIDIdleTime" as CFString, kCFAllocatorDefault, 0)?
            .takeRetainedValue() as? NSNumber else { return 0 }
        return Int(value.uint64Value / 1_000_000_000)
    }
}

public enum DeviceInfo {
    /// The local host name, which matches the inventory's hostname field.
    public static func hostname() -> String {
        if let name = SCDynamicStoreCopyLocalHostName(nil) as String?, !name.isEmpty { return name }
        return ProcessInfo.processInfo.hostName.components(separatedBy: ".").first ?? "unknown"
    }

    public static func serial() -> String {
        let service = IOServiceGetMatchingService(kIOMainPortDefault, IOServiceMatching("IOPlatformExpertDevice"))
        guard service != 0 else { return "unknown" }
        defer { IOObjectRelease(service) }
        let value = IORegistryEntryCreateCFProperty(service, kIOPlatformSerialNumberKey as CFString, kCFAllocatorDefault, 0)?
            .takeRetainedValue() as? String
        return value ?? "unknown"
    }

    /// Seconds since boot, so the first event after a start-up can say boot.
    public static func uptime() -> TimeInterval {
        var boottime = timeval()
        var size = MemoryLayout<timeval>.size
        var mib: [Int32] = [CTL_KERN, KERN_BOOTTIME]
        guard sysctl(&mib, 2, &boottime, &size, nil, 0) == 0 else { return .infinity }
        return Date().timeIntervalSince1970 - TimeInterval(boottime.tv_sec)
    }
}
