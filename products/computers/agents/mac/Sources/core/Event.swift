import Foundation

/// One event, exactly as core/contract/event.schema.json defines it.
public struct PulseEvent: Codable, Equatable, Sendable {
    public enum Kind: String, Codable, Sendable {
        case heartbeat, login, logout, lock, unlock, boot, shutdown
    }

    public struct Device: Codable, Equatable, Sendable { public var hostname: String; public var serial: String }
    public struct Session: Codable, Equatable, Sendable { public var active: Bool; public var locked: Bool; public var idleSeconds: Int }
    public struct Agent: Codable, Equatable, Sendable { public var version: String; public var platform: String }

    public var v = 1
    public var type: Kind
    public var ts: String
    public var device: Device
    public var session: Session
    public var agent: Agent

    public init(type: Kind, at date: Date, hostname: String, serial: String, snapshot: SessionSnapshot, version: String) {
        self.type = type
        self.ts = Self.timestamp(date)
        self.device = Device(hostname: String(hostname.prefix(63)), serial: String(serial.prefix(64)))
        self.session = Session(active: snapshot.active, locked: snapshot.locked, idleSeconds: max(0, snapshot.idleSeconds))
        self.agent = Agent(version: String(version.prefix(32)), platform: "mac")
    }

    public static func timestamp(_ date: Date) -> String {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        f.timeZone = TimeZone(identifier: "UTC")
        return f.string(from: date)
    }

    /// The event a change between two snapshots stands for, or nil when nothing a seat
    /// cares about changed. Sign-in and sign-out outrank locking.
    public static func change(from old: SessionSnapshot?, to new: SessionSnapshot) -> Kind? {
        guard let old else { return nil }
        if !old.active && new.active { return .login }
        if old.active && !new.active { return .logout }
        if !old.locked && new.locked { return .lock }
        if old.locked && !new.locked { return .unlock }
        return nil
    }

    public func json() throws -> Data {
        let e = JSONEncoder()
        e.outputFormatting = [.sortedKeys]
        return try e.encode(self)
    }
}
