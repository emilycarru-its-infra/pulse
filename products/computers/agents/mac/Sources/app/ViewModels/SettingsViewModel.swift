//
//  The Prefs page's values. Reads what the agent reads (a profile's value wins), and
//  saves each change through the helper a moment after the last edit, asking for an
//  administrator the first time. Managed keys are never written, and the ingest key is
//  status only: never read into the window and never saved from it.
//

import Foundation
import PulseAgentCore

@Observable
@MainActor
final class SettingsViewModel {
    enum SaveStatus: Equatable { case idle, saving, saved, failed(String) }

    var ingestURL = "" { didSet { changed(.ingestURL) } }
    /// The ingest key's status. Its value never enters the app.
    enum SecretState: Equatable { case notSet, set, managed }
    private(set) var ingestKeyState: SecretState = .notSet
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
        ingestKeyState = isManaged(.ingestKey) ? .managed
            : (PulseSettings.isSet(.ingestKey) ? .set : .notSet)
        checkInterval = s.checkInterval
        heartbeatInterval = s.heartbeatInterval
        verboseLogging = s.verboseLogging
        certificate = DeviceIdentity.findCertificate()
        services = LaunchdJob.readAll()
        dirty.removeAll()
    }

    private func changed(_ key: PulseSettings.Key) {
        guard !loading, !isManaged(key), !HelperPolicy.readOnlyKeys.contains(key) else { return }
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
        case .ingestKey: return nil
        case .checkInterval: return .some(min(max(checkInterval, PulseSettings.checkRange.lowerBound), PulseSettings.checkRange.upperBound))
        case .heartbeatInterval: return .some(min(max(heartbeatInterval, PulseSettings.heartbeatRange.lowerBound), PulseSettings.heartbeatRange.upperBound))
        case .verboseLogging: return .some(verboseLogging)
        }
    }

    private func save() async {
        guard let client else { return }
        let keys = dirty.filter { !isManaged($0) && !HelperPolicy.readOnlyKeys.contains($0) }
        dirty.removeAll()
        let writes = keys.compactMap { key in value(for: key).map { (key, $0) } }
        guard !writes.isEmpty else { return }
        // The first save of the session asks for an administrator; a cancel puts the
        // fields back to what is on disk.
        guard client.isUnlocked || client.unlock() else {
            load()
            saveStatus = .failed("Not saved: an administrator must approve the change.")
            return
        }
        saveStatus = .saving
        var refused: [String] = []
        for (key, value) in writes {
            let ok = await withCheckedContinuation { (c: CheckedContinuation<Bool, Never>) in
                client.set(key, value) { c.resume(returning: $0) }
            }
            if !ok { refused.append(key.rawValue) }
        }
        if refused.isEmpty {
            saveStatus = .saved
            try? await Task.sleep(for: .seconds(2.5))
            if saveStatus == .saved { saveStatus = .idle }
        } else {
            saveStatus = .failed("Not saved: \(refused.joined(separator: ", ")). \(client.connectionError ?? "The helper refused the change.")")
        }
    }
}
