import Foundation
import Security
import PulseAgentCore

final class HelperCommandRunner: NSObject, HelperXPCProtocol, @unchecked Sendable {
    // `process` is only touched on the connection's serial XPC queue.
    private let connection: NSXPCConnection
    private var process: Process?

    init(connection: NSXPCConnection) {
        self.connection = connection
    }

    /// The CLI beside this helper in the app bundle; the fixed install path is the fallback.
    static let cliURL: URL = {
        let own = URL(fileURLWithPath: CommandLine.arguments[0]).resolvingSymlinksInPath()
        let sibling = own.deletingLastPathComponent().appendingPathComponent(PulseConstants.cliName)
        if FileManager.default.isExecutableFile(atPath: sibling.path) { return sibling }
        return URL(fileURLWithPath: PulseConstants.cliPath)
    }()

    func runCommand(arguments: [String]) {
        let client = connection.remoteObjectProxy as? HelperXPCClientProtocol
        guard HelperPolicy.allowsCommand(arguments), process == nil else {
            client?.didEncounterError("The helper only runs send and status, one at a time")
            client?.runDidComplete(success: false, exitCode: -1)
            return
        }
        let task = Process()
        task.executableURL = Self.cliURL
        task.arguments = arguments
        let pipe = Pipe()
        task.standardOutput = pipe
        task.standardError = pipe
        process = task
        let handle = pipe.fileHandleForReading
        handle.readabilityHandler = { h in
            let data = h.availableData
            guard !data.isEmpty else { h.readabilityHandler = nil; return }
            for line in String(decoding: data, as: UTF8.self).components(separatedBy: .newlines) where !line.isEmpty {
                client?.didReceiveOutput(line)
            }
        }
        task.terminationHandler = { [weak self] proc in
            handle.readabilityHandler = nil
            let rest = handle.readDataToEndOfFile()
            for line in String(decoding: rest, as: UTF8.self).components(separatedBy: .newlines) where !line.isEmpty {
                client?.didReceiveOutput(line)
            }
            client?.runDidComplete(success: proc.terminationStatus == 0, exitCode: proc.terminationStatus)
            self?.process = nil
        }
        do {
            try task.run()
        } catch {
            client?.didEncounterError("Could not start \(PulseConstants.cliName): \(error.localizedDescription)")
            client?.runDidComplete(success: false, exitCode: -1)
            process = nil
        }
    }

    func stopCommand() {
        process?.terminate()
        process = nil
    }

    func setPreference(key: String, stringValue: String, domain: String, authorization: Data, withReply reply: @escaping (Bool) -> Void) {
        reply(write(key, stringValue as CFString, .string, domain, authorization))
    }

    func setBoolPreference(key: String, boolValue: Bool, domain: String, authorization: Data, withReply reply: @escaping (Bool) -> Void) {
        reply(write(key, boolValue as CFPropertyList, .bool, domain, authorization))
    }

    func setIntPreference(key: String, intValue: Int, domain: String, authorization: Data, withReply reply: @escaping (Bool) -> Void) {
        reply(write(key, intValue as CFNumber as CFPropertyList, .int, domain, authorization))
    }

    func removePreference(key: String, domain: String, authorization: Data, withReply reply: @escaping (Bool) -> Void) {
        reply(write(key, nil, nil, domain, authorization))
    }

    func getHelperVersion(withReply reply: @escaping (String) -> Void) {
        reply(PulseConstants.version)
    }

    /// One machine-level value, to /Library/Preferences where the agent reads it.
    private func write(_ key: String, _ value: CFPropertyList?, _ kind: PulseSettings.Key.Kind?, _ domain: String,
                       _ authorization: Data) -> Bool {
        guard Self.isAdminAuthorized(authorization) else {
            NSLog("managedpresencebeacon helper refused a write to %@: no administrator authorization", key)
            return false
        }
        let decision = HelperPolicy.evaluate(domain: domain, key: key, kind: kind) { PulseSettings.isManaged($0) }
        guard decision == .allow else {
            NSLog("managedpresencebeacon helper refused a write to %@ in %@: %@", key, domain, String(describing: decision))
            return false
        }
        let d = PulseConstants.domain as CFString
        CFPreferencesSetValue(key as CFString, value, d, kCFPreferencesAnyUser, kCFPreferencesAnyHost)
        return CFPreferencesSynchronize(d, kCFPreferencesAnyUser, kCFPreferencesAnyHost)
    }

    /// True when `externalForm` is an authorization an administrator granted to the app.
    static func isAdminAuthorized(_ externalForm: Data) -> Bool {
        guard externalForm.count == MemoryLayout<AuthorizationExternalForm>.size else { return false }
        var form = AuthorizationExternalForm()
        withUnsafeMutableBytes(of: &form) { buffer in
            _ = externalForm.copyBytes(to: buffer)
        }
        var authRef: AuthorizationRef?
        guard AuthorizationCreateFromExternalForm(&form, &authRef) == errAuthorizationSuccess, let authRef else {
            return false
        }
        defer { AuthorizationFree(authRef, []) }
        return HelperPolicy.adminRight.withCString { name in
            var item = AuthorizationItem(name: name, valueLength: 0, value: nil, flags: 0)
            return withUnsafeMutablePointer(to: &item) { itemPointer in
                var rights = AuthorizationRights(count: 1, items: itemPointer)
                return AuthorizationCopyRights(authRef, &rights, nil, [.extendRights], nil) == errAuthorizationSuccess
            }
        }
    }
}
