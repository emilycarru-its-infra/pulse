import Foundation

/// The reporting loop: look every check interval, send at once when someone signs in or
/// out or the screen locks or unlocks, and otherwise send a heartbeat every heartbeat
/// interval. A failed send is dropped; the next heartbeat brings the seat up to date.
public actor Agent {
    private let log = PulseLog.shared
    private var settings: PulseSettings
    private var last: SessionSnapshot?
    private var lastSent = Date.distantPast
    private let hostname = DeviceInfo.hostname()
    private let serial = DeviceInfo.serial()

    public init(settings: PulseSettings = .load()) {
        self.settings = settings
    }

    /// Looks once and sends whatever is due. `force` sends a heartbeat regardless.
    @discardableResult
    public func tick(force: Bool = false, now: Date = Date()) async -> SendResult? {
        settings = .load()
        log.verbose = settings.verboseLogging || log.verbose
        let snapshot = SessionReader.snapshot()
        let kind: PulseEvent.Kind?
        if last == nil && DeviceInfo.uptime() < 300 {
            kind = .boot
        } else if let change = PulseEvent.change(from: last, to: snapshot) {
            kind = change
        } else if force || now.timeIntervalSince(lastSent) >= Double(settings.heartbeatInterval) {
            kind = .heartbeat
        } else {
            kind = nil
        }
        last = snapshot
        guard let kind else { return nil }
        lastSent = now
        return await send(kind, snapshot: snapshot, at: now)
    }

    public func send(_ kind: PulseEvent.Kind, snapshot: SessionSnapshot = SessionReader.snapshot(), at now: Date = Date()) async -> SendResult {
        let event = PulseEvent(type: kind, at: now, hostname: hostname, serial: serial, snapshot: snapshot, version: PulseConstants.version)
        let identity = DeviceIdentity.find()
        if identity == nil { log.warn("No usable Intune agent certificate in the System keychain; sending without one") }
        let result = await Sender(settings: settings, identity: identity).send(event)
        result.save()
        let what = "\(kind.rawValue) active=\(snapshot.active) locked=\(snapshot.locked) idle=\(snapshot.idleSeconds)s"
        if result.ok {
            log.info("Sent \(what): HTTP \(result.status ?? 0)\(result.identity.map { " as \($0)" } ?? "")")
        } else {
            log.error("Could not send \(what): \(result.error ?? "unknown error")")
        }
        return result
    }

    public func interval() -> Int { settings.checkInterval }
}
