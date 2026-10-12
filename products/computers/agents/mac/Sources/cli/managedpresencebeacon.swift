import Foundation
import PulseAgentCore

/// managedpresencebeacon: reports whether this Mac's console is in use, for Pulse.
///
///   managedpresencebeacon run       the reporting loop the LaunchDaemon starts
///   managedpresencebeacon status    what the agent sees right now
///   managedpresencebeacon send      send one heartbeat now
///   managedpresencebeacon --version
@main
struct ManagedPresenceBeaconCLI {
    static func main() async {
        var args = Array(CommandLine.arguments.dropFirst())
        let verbose = args.contains("--verbose")
        args.removeAll { $0 == "--verbose" }
        let log = PulseLog.shared
        log.verbose = verbose

        switch args.first ?? "help" {
        case "--version", "version":
            print(PulseConstants.version)
        case "status":
            status(json: args.contains("--json"))
        case "send":
            log.echo = true
            let result = await Agent().send(.heartbeat)
            exit(result.ok ? 0 : 1)
        case "run":
            await run()
        default:
            print("""
            usage: managedpresencebeacon run | status [--json] | send | --version   [--verbose]

              run      the reporting loop (started by the LaunchDaemon)
              status   what this Mac reports right now
              send     send one heartbeat now
            Settings come from the \(PulseConstants.domain) preference domain.
            """)
            exit(args.isEmpty || args.first == "help" ? 0 : 64)
        }
    }

    static func status(json: Bool) {
        let s = PulseSettings.load()
        let snap = SessionReader.snapshot()
        let identity = DeviceIdentity.find()
        let cert = identity.map { ($0.subject, $0.expires) } ?? DeviceIdentity.findCertificate().map { ($0.subject, $0.expires) }
        let canSign = identity?.canSign() ?? false
        let last = SendResult.load()
        if json {
            var o: [String: Any] = [
                "version": PulseConstants.version, "hostname": DeviceInfo.hostname(), "serial": DeviceInfo.serial(),
                "active": snap.active, "locked": snap.locked, "idleSeconds": snap.idleSeconds, "seatState": snap.seatState,
                "ingestURL": s.ingestURL, "ingestKeySet": !s.ingestKey.isEmpty,
                "checkInterval": s.checkInterval, "heartbeatInterval": s.heartbeatInterval,
                "certificate": cert?.0 ?? NSNull(), "certificateUsable": canSign,
            ]
            if let id = identity?.deviceID { o["intuneDeviceID"] = id }
            if let last, let d = try? JSONEncoder().encode(last), let j = try? JSONSerialization.jsonObject(with: d) { o["lastSend"] = j }
            if let d = try? JSONSerialization.data(withJSONObject: o, options: [.prettyPrinted, .sortedKeys]) {
                print(String(decoding: d, as: UTF8.self))
            }
            return
        }
        let managed = PulseSettings.Key.allCases.filter { PulseSettings.isManaged($0) }.map(\.rawValue)
        print("""
        \(PulseConstants.appName) \(PulseConstants.version)
          Device       \(DeviceInfo.hostname())  serial \(DeviceInfo.serial())
          Signed in    \(snap.active ? "yes" : "no")
          Locked       \(snap.locked ? "yes" : "no")
          Idle         \(snap.idleSeconds) s
          Seat state   \(snap.seatState)
          Ingest URL   \(s.ingestURL.isEmpty ? "(not set)" : s.ingestURL)
          Ingest key   \(s.ingestKey.isEmpty ? "(not set)" : "set")
          Intervals    check \(s.checkInterval) s, heartbeat \(s.heartbeatInterval) s
          Managed      \(managed.isEmpty ? "none" : managed.joined(separator: ", "))
          Certificate  \(cert.map { "\($0.0)\($0.1.map { ", expires \(PulseEvent.timestamp($0))" } ?? "")" } ?? "not found in the System keychain")
          Usable       \(identity == nil ? (cert == nil ? "no" : "no (run as root to use its key)") : (canSign ? "yes, signs without a prompt" : "no"))
        """)
        if let id = identity?.deviceID { print("  Intune ID    \(id)") }
        if let last {
            print("  Last send    \(last.at) \(last.type): \(last.ok ? "HTTP \(last.status ?? 0)" : (last.error ?? "failed"))")
        }
    }

    static func run() async {
        let log = PulseLog.shared
        let agent = Agent()
        log.info("\(PulseConstants.cliName) \(PulseConstants.version) starting")

        // On shutdown launchd sends SIGTERM: report the seat off, briefly, then go.
        signal(SIGTERM, SIG_IGN)
        let term = DispatchSource.makeSignalSource(signal: SIGTERM, queue: .global())
        term.setEventHandler {
            Task {
                _ = await agent.send(.shutdown)
                log.info("Stopping")
                exit(0)
            }
        }
        term.resume()

        while true {
            await agent.tick()
            let wait = await agent.interval()
            try? await Task.sleep(for: .seconds(wait))
        }
    }
}
