import Foundation
import LocalAuthentication
import Security

/// The Intune agent's client certificate, which the agent presents to the ingest server as
/// proof of which Mac is reporting. Intune installs it in the System keychain as
/// "IntuneMDMAgent-<Intune device id>", issued by "Microsoft Intune MDM Agent CA", with a
/// key root can use without a prompt. Only the System keychain is searched, and never with
/// user interface, so the agent can never raise a keychain dialog.
public struct DeviceIdentity: @unchecked Sendable {
    public static let subjectPrefix = "IntuneMDMAgent-"
    public static let issuerName = "Microsoft Intune MDM Agent CA"
    public static let systemKeychain = "/Library/Keychains/System.keychain"

    public let identity: SecIdentity
    public let certificate: SecCertificate
    public let subject: String
    public let expires: Date?

    /// The Intune device id carried in the subject.
    public var deviceID: String { String(subject.dropFirst(Self.subjectPrefix.count)) }

    /// Finds the identity. Returns nil when it is missing, or when this process cannot
    /// reach its key (a standard user can see the certificate but not use it).
    public static func find() -> DeviceIdentity? {
        for item in items(kSecClassIdentity) {
            guard let ref = item[kSecValueRef as String], CFGetTypeID(ref as CFTypeRef) == SecIdentityGetTypeID() else { continue }
            let identity = ref as! SecIdentity
            var cert: SecCertificate?
            guard SecIdentityCopyCertificate(identity, &cert) == errSecSuccess, let cert, matches(cert) else { continue }
            return DeviceIdentity(identity: identity, certificate: cert,
                                  subject: SecCertificateCopySubjectSummary(cert) as String? ?? "",
                                  expires: expiry(of: cert))
        }
        return nil
    }

    /// The certificate alone, which any user can read, for the app's Prefs page.
    public static func findCertificate() -> (subject: String, expires: Date?)? {
        for item in items(kSecClassCertificate) {
            guard let ref = item[kSecValueRef as String], CFGetTypeID(ref as CFTypeRef) == SecCertificateGetTypeID() else { continue }
            let cert = ref as! SecCertificate
            if matches(cert) { return (SecCertificateCopySubjectSummary(cert) as String? ?? "", expiry(of: cert)) }
        }
        return nil
    }

    /// True when this process can sign with the key without any prompt.
    public func canSign() -> Bool {
        var key: SecKey?
        guard SecIdentityCopyPrivateKey(identity, &key) == errSecSuccess, let key else { return false }
        var error: Unmanaged<CFError>?
        return SecKeyCreateSignature(key, .rsaSignatureMessagePKCS1v15SHA256, Data("managedpulse".utf8) as CFData, &error) != nil
    }

    static func matches(_ cert: SecCertificate) -> Bool {
        guard let subject = SecCertificateCopySubjectSummary(cert) as String?, subject.hasPrefix(subjectPrefix) else { return false }
        return issuer(of: cert)?.contains(issuerName) ?? false
    }

    private static func items(_ cls: CFString) -> [[String: Any]] {
        // SecKeychainOpen is deprecated, but it is still the only way to name the System
        // keychain as the one place to search, which keeps a user's keychains out of it.
        var keychain: SecKeychain?
        guard SecKeychainOpen(systemKeychain, &keychain) == errSecSuccess, let keychain else { return [] }
        SecKeychainSetUserInteractionAllowed(false)
        let query: [String: Any] = [
            kSecClass as String: cls,
            kSecMatchLimit as String: kSecMatchLimitAll,
            kSecMatchSearchList as String: [keychain],
            kSecReturnRef as String: true,
            kSecReturnAttributes as String: true,
            kSecUseAuthenticationContext as String: noInteraction(),
        ]
        var out: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &out) == errSecSuccess else { return [] }
        return out as? [[String: Any]] ?? []
    }

    private static func noInteraction() -> LAContext {
        let context = LAContext()
        context.interactionNotAllowed = true
        return context
    }

    private static func values(_ cert: SecCertificate, _ oid: CFString) -> [String: Any]? {
        (SecCertificateCopyValues(cert, [oid] as CFArray, nil) as? [String: Any])?[oid as String] as? [String: Any]
    }

    static func issuer(of cert: SecCertificate) -> String? {
        guard let entries = values(cert, kSecOIDX509V1IssuerName)?[kSecPropertyKeyValue as String] as? [[String: Any]] else { return nil }
        return entries.compactMap { $0[kSecPropertyKeyValue as String] as? String }.joined(separator: ", ")
    }

    static func expiry(of cert: SecCertificate) -> Date? {
        guard let n = values(cert, kSecOIDX509V1ValidityNotAfter)?[kSecPropertyKeyValue as String] as? NSNumber else { return nil }
        return Date(timeIntervalSinceReferenceDate: n.doubleValue)
    }
}
