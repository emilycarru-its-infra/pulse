//
//  The connection to the privileged helper: preference writes, and the CLI's send and
//  status commands with their output streamed back.
//

import Foundation
import ServiceManagement
import PulseAgentCore

@Observable
@MainActor
final class XPCClient: NSObject {
    var outputLines: [OutputLine] = []
    var isRunning = false
    var lastExitCode: Int32?
    var helperStatus: HelperStatus = .unknown
    var connectionError: String?
    private(set) var isUnlocked = false

    private var connection: NSXPCConnection?
    private let admin = AdminAuthorization()

    struct OutputLine: Identifiable {
        let id = UUID()
        let text: String
        let level: Level
        enum Level { case info, debug, warning, error, success }
    }

    enum HelperStatus: String {
        case unknown = "Unknown"
        case registered = "Running"
        case notRegistered = "Not installed"
        case requiresApproval = "Needs approval in Login Items"
    }

    func connect() {
        guard connection == nil else { return }
        let conn = NSXPCConnection(machServiceName: PulseConstants.helperLabel, options: .privileged)
        conn.remoteObjectInterface = NSXPCInterface(with: HelperXPCProtocol.self)
        conn.exportedInterface = NSXPCInterface(with: HelperXPCClientProtocol.self)
        conn.exportedObject = self
        conn.invalidationHandler = makeHandler("The connection to the helper ended", dropConnection: true)
        conn.interruptionHandler = makeHandler("The helper stopped", dropConnection: false)
        conn.resume()
        connection = conn
        connectionError = nil
        proxy { p in
            p.getHelperVersion { _ in
                Task { @MainActor in
                    self.helperStatus = .registered
                    self.connectionError = nil
                }
            }
        }
    }

    func checkHelperStatus() {
        switch SMAppService.daemon(plistName: PulseConstants.helperPlistName).status {
        case .enabled: helperStatus = .registered
        case .requiresApproval: helperStatus = .requiresApproval
        case .notRegistered, .notFound: if helperStatus != .registered { helperStatus = .notRegistered }
        @unknown default: helperStatus = .unknown
        }
    }

    // MARK: Commands

    func run(_ arguments: [String]) {
        guard !isRunning else { return }
        isRunning = true
        lastExitCode = nil
        outputLines.removeAll()
        connect()
        proxy { $0.runCommand(arguments: arguments) }
    }

    func stop() {
        proxy { $0.stopCommand() }
        isRunning = false
        outputLines.append(OutputLine(text: "[WARNING] Stopped.", level: .warning))
    }

    // MARK: Administrator

    /// Prompts for an administrator. Prefs stay editable until `lock()` or the app quits.
    @discardableResult
    func unlock() -> Bool {
        isUnlocked = admin.unlock()
        return isUnlocked
    }

    func lock() {
        admin.lock()
        isUnlocked = false
    }

    // MARK: Preferences

    /// Each write replies whether the helper took it.
    func set(_ key: PulseSettings.Key, _ value: Any?, reply: @escaping @Sendable (Bool) -> Void) {
        connect()
        let domain = PulseConstants.domain
        guard connection != nil, let auth = admin.externalForm else { reply(false); return }
        proxy(onError: { reply(false) }) { p in
            switch value {
            case nil: p.removePreference(key: key.rawValue, domain: domain, authorization: auth, withReply: reply)
            case let s as String: p.setPreference(key: key.rawValue, stringValue: s, domain: domain, authorization: auth, withReply: reply)
            case let b as Bool: p.setBoolPreference(key: key.rawValue, boolValue: b, domain: domain, authorization: auth, withReply: reply)
            case let i as Int: p.setIntPreference(key: key.rawValue, intValue: i, domain: domain, authorization: auth, withReply: reply)
            default: reply(false)
            }
        }
    }

    // MARK: Private

    private nonisolated func makeHandler(_ message: String, dropConnection: Bool) -> @Sendable () -> Void {
        { [weak self] in
            Task { @MainActor [weak self] in
                if dropConnection { self?.connection = nil }
                self?.reportFailure(message)
            }
        }
    }

    private func reportFailure(_ message: String) {
        connectionError = message
        if isRunning {
            outputLines.append(OutputLine(text: "[ERROR] \(message). See the system log for \(PulseConstants.helperLabel).", level: .error))
            isRunning = false
        }
    }

    private func proxy(onError: (@Sendable () -> Void)? = nil, _ block: (HelperXPCProtocol) -> Void) {
        guard let conn = connection else { connectionError = "No connection to the helper"; onError?(); return }
        let handler: @Sendable (any Error) -> Void = { [weak self] error in
            onError?()
            Task { @MainActor [weak self] in self?.reportFailure(error.localizedDescription) }
        }
        guard let p = conn.remoteObjectProxyWithErrorHandler(handler) as? HelperXPCProtocol else {
            connectionError = "Could not reach the helper"
            onError?()
            return
        }
        block(p)
    }
}

extension XPCClient: HelperXPCClientProtocol {
    nonisolated func didReceiveOutput(_ line: String) {
        let level = Self.level(of: line)
        Task { @MainActor in outputLines.append(OutputLine(text: line, level: level)) }
    }

    nonisolated func runDidComplete(success: Bool, exitCode: Int32) {
        Task { @MainActor in
            isRunning = false
            lastExitCode = exitCode
        }
    }

    nonisolated func didEncounterError(_ message: String) {
        Task { @MainActor in
            connectionError = message
            outputLines.append(OutputLine(text: "[ERROR] \(message)", level: .error))
        }
    }

    nonisolated static func level(of line: String) -> OutputLine.Level {
        if line.contains("] ERROR") || line.contains("[ERROR]") { return .error }
        if line.contains("] WARN") || line.contains("[WARNING]") { return .warning }
        if line.contains("] DEBUG") { return .debug }
        if line.contains("] INFO  Sent") { return .success }
        return .info
    }
}
