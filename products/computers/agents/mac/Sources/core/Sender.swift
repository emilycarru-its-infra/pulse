import Foundation

/// What happened to one send, kept for the app's Run tab.
public struct SendResult: Codable, Equatable, Sendable {
    public var at: String
    public var type: String
    public var status: Int?
    public var error: String?
    /// The certificate subject presented, when the server asked for one.
    public var identity: String?

    public var ok: Bool { (status ?? 0) / 100 == 2 }

    public func save(to path: String = PulseConstants.lastSendPath) {
        guard let data = try? JSONEncoder().encode(self) else { return }
        try? data.write(to: URL(fileURLWithPath: path), options: .atomic)
    }

    public static func load(from path: String = PulseConstants.lastSendPath) -> SendResult? {
        guard let data = FileManager.default.contents(atPath: path) else { return nil }
        return try? JSONDecoder().decode(SendResult.self, from: data)
    }
}

/// Posts events to the ingest URL. When the server asks for a client certificate, it
/// presents the device identity; a configured ingest key goes in X-Pulse-Key.
public final class Sender: NSObject, URLSessionTaskDelegate, @unchecked Sendable {
    private let settings: PulseSettings
    private let identity: DeviceIdentity?
    private let lock = NSLock()
    private var presented: String?

    public init(settings: PulseSettings, identity: DeviceIdentity?) {
        self.settings = settings
        self.identity = identity
    }

    public func send(_ event: PulseEvent, timeout: TimeInterval = 10) async -> SendResult {
        var result = SendResult(at: PulseEvent.timestamp(Date()), type: event.type.rawValue)
        guard let url = URL(string: settings.ingestURL), url.scheme == "https" || url.scheme == "http" else {
            result.error = settings.ingestURL.isEmpty ? "No ingest URL is set" : "The ingest URL is not valid"
            return result
        }
        var request = URLRequest(url: url, timeoutInterval: timeout)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("\(PulseConstants.cliName)/\(PulseConstants.version)", forHTTPHeaderField: "User-Agent")
        if !settings.ingestKey.isEmpty { request.setValue(settings.ingestKey, forHTTPHeaderField: "X-Pulse-Key") }
        do {
            request.httpBody = try event.json()
            let config = URLSessionConfiguration.ephemeral
            config.timeoutIntervalForResource = timeout
            let session = URLSession(configuration: config, delegate: self, delegateQueue: nil)
            defer { session.finishTasksAndInvalidate() }
            let (_, response) = try await session.data(for: request)
            result.status = (response as? HTTPURLResponse)?.statusCode
            if !result.ok { result.error = "The server answered \(result.status.map(String.init) ?? "nothing")" }
        } catch {
            result.error = error.localizedDescription
        }
        result.identity = lock.withLock { presented }
        return result
    }

    public func urlSession(_ session: URLSession, task: URLSessionTask, didReceive challenge: URLAuthenticationChallenge)
        async -> (URLSession.AuthChallengeDisposition, URLCredential?) {
        guard challenge.protectionSpace.authenticationMethod == NSURLAuthenticationMethodClientCertificate else {
            return (.performDefaultHandling, nil)
        }
        guard let identity else { return (.performDefaultHandling, nil) }
        lock.withLock { presented = identity.subject }
        return (.useCredential, URLCredential(identity: identity.identity, certificates: nil, persistence: .forSession))
    }
}
