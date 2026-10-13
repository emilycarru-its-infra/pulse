import Foundation

/// Protocol exposed by the privileged helper. Every method runs as root.
@objc public protocol HelperXPCProtocol: Sendable {
    /// Runs the CLI with one of the commands the helper allows; output streams back
    /// through the client protocol.
    func runCommand(arguments: [String])
    func stopCommand()

    /// Machine-level preference writes (any user, any host), refused for a key a
    /// configuration profile manages. `authorization` is the AuthorizationExternalForm the
    /// app got when an administrator unlocked the window; a write without it is refused.
    func setPreference(key: String, stringValue: String, domain: String, authorization: Data, withReply reply: @escaping (Bool) -> Void)
    func setBoolPreference(key: String, boolValue: Bool, domain: String, authorization: Data, withReply reply: @escaping (Bool) -> Void)
    func setIntPreference(key: String, intValue: Int, domain: String, authorization: Data, withReply reply: @escaping (Bool) -> Void)
    func removePreference(key: String, domain: String, authorization: Data, withReply reply: @escaping (Bool) -> Void)

    func getHelperVersion(withReply reply: @escaping (String) -> Void)
}

/// Callbacks from the helper to the app.
@objc public protocol HelperXPCClientProtocol: Sendable {
    func didReceiveOutput(_ line: String)
    func runDidComplete(success: Bool, exitCode: Int32)
    func didEncounterError(_ message: String)
}

/// Decides which requests the root helper accepts: only the Prefs page's keys, only in
/// this domain, never a managed key, never the ingest key, and only the CLI commands
/// the Run tab uses.
public enum HelperPolicy {
    public enum Decision: Equatable, Sendable { case allow, wrongDomain, unknownKey, wrongType, managed, readOnly }

    /// Keys the helper never writes or removes. The ingest key is set by a configuration
    /// profile only, so a local administrator cannot read or change it from the app.
    public static let readOnlyKeys: Set<PulseSettings.Key> = [.ingestKey]

    public static let commands: Set<String> = ["send", "status"]

    /// The right an administrator must hold to change a preference. Send and status
    /// need none, so a standard user can still use Run.
    public static let adminRight = "system.privilege.admin"

    public static func allowsCommand(_ arguments: [String]) -> Bool {
        guard let first = arguments.first, commands.contains(first) else { return false }
        return arguments.dropFirst().allSatisfy { $0 == "--verbose" }
    }

    /// `kind` is nil for a removal.
    public static func evaluate(domain: String, key: String, kind: PulseSettings.Key.Kind?,
                                isManaged: (PulseSettings.Key) -> Bool) -> Decision {
        guard domain == PulseConstants.domain else { return .wrongDomain }
        guard let k = PulseSettings.Key(rawValue: key) else { return .unknownKey }
        if readOnlyKeys.contains(k) { return .readOnly }
        if let kind, kind != k.kind { return .wrongType }
        if isManaged(k) { return .managed }
        return .allow
    }
}
