//
//  The Prefs page's values. Reads what the agent reads (a profile's value wins), and
//  saves each change through the helper a moment after the last edit, once an
//  administrator has unlocked the window. Managed keys are never written.
//

import Foundation
import PulseAgentCore

@Observable
@MainActor
final class SettingsViewModel {
    enum SaveStatus: Equatable { case idle, saving, saved, failed(String) }

    var ingestURL = "" { didSet { changed(.ingestURL) } }
    /// A new key typed in; the stored one is never shown or re-saved.
    var ingestKey = "" { didSet { changed(.ingestKey) } }
    private(set) var hasStoredKey = false
    var checkInterval = 15 { didSet { changed(.checkInterval) } }
    var heartbeatInterval = 60 { didSet { changed(.heartbeatInterval) } }
    var verboseLogging = false { didSet { changed(.verboseLogging) } }

    private(set) var managed: Set<PulseSettings.Key> = []
    private(set) var saveStatus: SaveStatus = .idle
    private(set) var certificate: (subject: String, expires: Date?)?

    private var client: XPCClient?
    private var dirty: Set<PulseSettings.Key> = []
    private var saveTask: Task<Void, Never>?
    private var loading = false

    func configure(client: XPCClient) { self.client = client }

    func isManaged(_ key: PulseSettings.Key) -> Bool { managed.contains(key) }

    /// True when a profile sets at least one key, which shows the Prefs banner.
    var anyManaged: Bool { !managed.isEmpty }
    private(set) var services: [LaunchdJob] = []

    func load() {
        loading = true
        defer { loading = false }
        let s = PulseSettings.load()
        managed = Set(PulseSettings.Key.allCases.filter { PulseSettings.isManaged($0) })
        ingestURL = s.ingestURL
        hasStoredKey = !s.ingestKey.isEmpty
        ingestKey = ""
        checkInterval = s.checkInterval
        heartbeatInterval = s.heartbeatInterval
        verboseLogging = s.verboseLogging
        certificate = DeviceIdentity.findCertificate()
        services = LaunchdJob.readAll()
        dirty.removeAll()
    }

    private func changed(_ key: PulseSettings.Key) {
        guard !loading, !isManaged(key), client?.isUnlocked == true else { return }
        dirty.insert(key)
        saveTask?.cancel()
        saveTask = Task { [weak self] in
            try? await Task.sleep(for: .seconds(0.75))
            guard !Task.isCancelled else { return }
            await self?.save()
        }
    }

    private func value(for key: PulseSettings.Key) -> Any?? {
        switch key {
        case .ingestURL: return ingestURL.isEmpty ? .some(nil) : .some(ingestURL)
        case .ingestKey: return ingestKey.isEmpty ? nil : .some(ingestKey)
        case .checkInterval: return .some(min(max(checkInterval, PulseSettings.checkRange.lowerBound), PulseSettings.checkRange.upperBound))
        case .heartbeatInterval: return .some(min(max(heartbeatInterval, PulseSettings.heartbeatRange.lowerBound), PulseSettings.heartbeatRange.upperBound))
        case .verboseLogging: return .some(verboseLogging)
        }
    }

    private func save() async {
        guard let client else { return }
        let keys = dirty.filter { !isManaged($0) }
        dirty.removeAll()
        let writes = keys.compactMap { key in value(for: key).map { (key, $0) } }
        guard !writes.isEmpty else { return }
        saveStatus = .saving
        var refused: [String] = []
        for (key, value) in writes {
            let ok = await withCheckedContinuation { (c: CheckedContinuation<Bool, Never>) in
                client.set(key, value) { c.resume(returning: $0) }
            }
            if !ok { refused.append(key.rawValue) }
        }
        if refused.isEmpty {
            if writes.contains(where: { $0.0 == .ingestKey }) {
                hasStoredKey = true
                loading = true
                ingestKey = ""
                loading = false
            }
            saveStatus = .saved
            try? await Task.sleep(for: .seconds(2.5))
            if saveStatus == .saved { saveStatus = .idle }
        } else {
            saveStatus = .failed("Not saved: \(refused.joined(separator: ", ")). \(client.connectionError ?? "The helper refused the change.")")
        }
    }
}
