//
//  Privileged helper, run as root by launchd. It writes the agent's machine-level
//  preferences and runs the CLI's send and status commands for the app.
//

import Foundation
import os
import Security
import PulseAgentCore

private let log = Logger(subsystem: PulseConstants.helperLabel, category: "xpc")

/// The Team ID this helper is signed with. The app is signed by the same identity, so
/// the helper trusts exactly its own team. Nil when unsigned or ad-hoc signed.
private let ownTeamID: String? = {
    var selfCode: SecCode?
    guard SecCodeCopySelf([], &selfCode) == errSecSuccess, let selfCode else { return nil }
    var staticCode: SecStaticCode?
    guard SecCodeCopyStaticCode(selfCode, [], &staticCode) == errSecSuccess, let staticCode else { return nil }
    var info: CFDictionary?
    guard SecCodeCopySigningInformation(staticCode, SecCSFlags(rawValue: kSecCSSigningInformation), &info) == errSecSuccess,
          let dict = info as? [String: Any] else { return nil }
    return dict[kSecCodeInfoTeamIdentifier as String] as? String
}()

final class HelperService: NSObject, NSXPCListenerDelegate, Sendable {
    func listener(_ listener: NSXPCListener, shouldAcceptNewConnection connection: NSXPCConnection) -> Bool {
        // Only a client signed by this helper's own team may connect.
        guard let teamID = ownTeamID else {
            log.error("Rejecting XPC client pid \(connection.processIdentifier): this helper has no Team ID (unsigned or ad-hoc build)")
            return false
        }
        // Checked against the client's audit token on every message.
        connection.setCodeSigningRequirement("anchor apple generic and certificate leaf[subject.OU] = \"\(teamID)\"")
        connection.exportedInterface = NSXPCInterface(with: HelperXPCProtocol.self)
        connection.remoteObjectInterface = NSXPCInterface(with: HelperXPCClientProtocol.self)
        let runner = HelperCommandRunner(connection: connection)
        connection.exportedObject = runner
        connection.invalidationHandler = { [weak runner] in runner?.stopCommand() }
        connection.resume()
        return true
    }
}

let delegate = HelperService()
let listener = NSXPCListener(machServiceName: PulseConstants.helperLabel)
listener.delegate = delegate
listener.resume()
RunLoop.current.run()
