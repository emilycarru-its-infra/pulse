//
//  Asks an administrator to authenticate the first time Prefs saves a change, and keeps
//  the resulting authorization, which the helper checks before any preference write.
//  Run needs no administrator.
//

import Foundation
import Security
import PulseAgentCore

@MainActor
final class AdminAuthorization {
    private var authRef: AuthorizationRef?

    /// The external form the helper accepts, or nil while locked.
    private(set) var externalForm: Data?

    var isUnlocked: Bool { externalForm != nil }

    /// Shows the system's administrator prompt. True when an administrator authenticated.
    func unlock() -> Bool {
        lock()
        var ref: AuthorizationRef?
        guard AuthorizationCreate(nil, nil, [], &ref) == errAuthorizationSuccess, let ref else { return false }

        let status = HelperPolicy.adminRight.withCString { name -> OSStatus in
            var item = AuthorizationItem(name: name, valueLength: 0, value: nil, flags: 0)
            return withUnsafeMutablePointer(to: &item) { itemPointer in
                var rights = AuthorizationRights(count: 1, items: itemPointer)
                return AuthorizationCopyRights(ref, &rights, nil, [.interactionAllowed, .extendRights, .preAuthorize], nil)
            }
        }
        guard status == errAuthorizationSuccess else {
            AuthorizationFree(ref, [])
            return false
        }

        var form = AuthorizationExternalForm()
        guard AuthorizationMakeExternalForm(ref, &form) == errAuthorizationSuccess else {
            AuthorizationFree(ref, [.destroyRights])
            return false
        }
        authRef = ref
        externalForm = withUnsafeBytes(of: &form) { Data($0) }
        return true
    }

    /// Discards the authorization, so a further change needs a new prompt.
    func lock() {
        if let authRef { AuthorizationFree(authRef, [.destroyRights]) }
        authRef = nil
        externalForm = nil
    }
}
