import Foundation

/// The agent's settings, read from the `com.github.managedpulse` preference domain. A
/// configuration profile for that domain manages any of them; otherwise the app writes
/// them to /Library/Preferences through the helper.
public struct PulseSettings: Equatable, Sendable {
    public enum Key: String, CaseIterable, Sendable {
        case ingestURL = "IngestURL"
        case ingestKey = "IngestKey"
        case checkInterval = "CheckInterval"
        case heartbeatInterval = "HeartbeatInterval"
        case verboseLogging = "VerboseLogging"

        /// The type the helper accepts for each key.
        public var kind: Kind {
            switch self {
            case .ingestURL, .ingestKey: .string
            case .checkInterval, .heartbeatInterval: .int
            case .verboseLogging: .bool
            }
        }

        public enum Kind: Sendable { case string, int, bool }
    }

    public static let checkRange = 5...120
    public static let heartbeatRange = 30...600

    public var ingestURL: String = ""
    /// A shared ingest key, sent as X-Pulse-Key. Optional; the device certificate is the
    /// main proof of identity.
    public var ingestKey: String = ""
    public var checkInterval: Int = 15
    public var heartbeatInterval: Int = 60
    public var verboseLogging: Bool = false

    public init() {}

    /// Reads every setting the way the agent sees it: a profile's value first, then
    /// /Library/Preferences, then the default.
    public static func load(domain: String = PulseConstants.domain) -> PulseSettings {
        let d = domain as CFString
        CFPreferencesAppSynchronize(d)
        func value(_ key: Key) -> Any? { CFPreferencesCopyAppValue(key.rawValue as CFString, d) }
        var s = PulseSettings()
        if let v = value(.ingestURL) as? String { s.ingestURL = v.trimmingCharacters(in: .whitespaces) }
        if let v = value(.ingestKey) as? String { s.ingestKey = v }
        if let v = int(value(.checkInterval)) { s.checkInterval = clamp(v, checkRange) }
        if let v = int(value(.heartbeatInterval)) { s.heartbeatInterval = clamp(v, heartbeatRange) }
        if let v = value(.verboseLogging) as? Bool { s.verboseLogging = v }
        return s
    }

    /// True when a configuration profile sets the key. CFPreferences keeps the managed
    /// layer it loaded at start-up, so the managed preferences file is checked as well.
    public static func isManaged(_ key: Key, domain: String = PulseConstants.domain) -> Bool {
        if CFPreferencesAppValueIsForced(key.rawValue as CFString, domain as CFString) { return true }
        let path = "/Library/Managed Preferences/\(domain).plist"
        return (NSDictionary(contentsOfFile: path)?[key.rawValue]) != nil
    }

    static func int(_ value: Any?) -> Int? {
        if let n = value as? NSNumber { return n.intValue }
        if let s = value as? String { return Int(s) }
        return nil
    }

    static func clamp(_ v: Int, _ r: ClosedRange<Int>) -> Int { min(max(v, r.lowerBound), r.upperBound) }
}
