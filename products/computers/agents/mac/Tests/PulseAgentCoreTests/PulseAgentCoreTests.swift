import Foundation
import Testing
@testable import PulseAgentCore

@Test func changesBecomeEvents() {
    let idle = SessionSnapshot(active: false, locked: false, idleSeconds: 0)
    let user = SessionSnapshot(active: true, locked: false, idleSeconds: 3)
    let locked = SessionSnapshot(active: true, locked: true, idleSeconds: 3)
    #expect(PulseEvent.change(from: nil, to: user) == nil)
    #expect(PulseEvent.change(from: idle, to: user) == .login)
    #expect(PulseEvent.change(from: user, to: idle) == .logout)
    #expect(PulseEvent.change(from: user, to: locked) == .lock)
    #expect(PulseEvent.change(from: locked, to: user) == .unlock)
    #expect(PulseEvent.change(from: locked, to: idle) == .logout)
    #expect(PulseEvent.change(from: user, to: SessionSnapshot(active: true, locked: false, idleSeconds: 99)) == nil)
}

@Test func eventMatchesTheContract() throws {
    let snap = SessionSnapshot(active: true, locked: false, idleSeconds: 42)
    let date = Date(timeIntervalSince1970: 1_799_000_000)
    let e = PulseEvent(type: .heartbeat, at: date, hostname: "LAB-MAC-01", serial: "EXAMPLE-SERIAL", snapshot: snap, version: "2027.01.04.1705")
    let o = try #require(try JSONSerialization.jsonObject(with: e.json()) as? [String: Any])
    #expect(Set(o.keys) == ["v", "type", "ts", "device", "session", "agent"])
    #expect(o["v"] as? Int == 1)
    #expect((o["ts"] as? String)?.hasSuffix("Z") == true)
    #expect((o["session"] as? [String: Any])?["idleSeconds"] as? Int == 42)
    #expect((o["agent"] as? [String: Any])?["platform"] as? String == "mac")
    #expect(Set((o["device"] as? [String: Any])?.keys ?? [:].keys) == ["hostname", "serial"])
}

@Test func seatStateMirrorsTheServer() {
    #expect(SessionSnapshot(active: false, locked: false, idleSeconds: 0).seatState == "available")
    #expect(SessionSnapshot(active: true, locked: false, idleSeconds: 10).seatState == "in_use")
    #expect(SessionSnapshot(active: true, locked: true, idleSeconds: 10).seatState == "possibly_free")
    #expect(SessionSnapshot(active: true, locked: false, idleSeconds: 900).seatState == "possibly_free")
}

@Test func helperAcceptsOnlyThePrefsKeysAndCommands() {
    let never: (PulseSettings.Key) -> Bool = { _ in false }
    #expect(HelperPolicy.evaluate(domain: PulseConstants.domain, key: "IngestURL", kind: .string, isManaged: never) == .allow)
    #expect(HelperPolicy.evaluate(domain: "com.example.other", key: "IngestURL", kind: .string, isManaged: never) == .wrongDomain)
    #expect(HelperPolicy.evaluate(domain: PulseConstants.domain, key: "Nope", kind: .string, isManaged: never) == .unknownKey)
    #expect(HelperPolicy.evaluate(domain: PulseConstants.domain, key: "CheckInterval", kind: .string, isManaged: never) == .wrongType)
    #expect(HelperPolicy.evaluate(domain: PulseConstants.domain, key: "IngestURL", kind: nil, isManaged: { $0 == .ingestURL }) == .managed)
    #expect(HelperPolicy.evaluate(domain: PulseConstants.domain, key: "IngestKey", kind: .string, isManaged: never) == .readOnly)
    #expect(HelperPolicy.evaluate(domain: PulseConstants.domain, key: "IngestKey", kind: nil, isManaged: never) == .readOnly)
    #expect(HelperPolicy.allowsCommand(["send", "--verbose"]))
    #expect(HelperPolicy.allowsCommand(["status"]))
    #expect(!HelperPolicy.allowsCommand(["run"]))
    #expect(!HelperPolicy.allowsCommand(["send", "--other"]))
    #expect(!HelperPolicy.allowsCommand([]))
}

@Test func settingsClampToTheirRanges() {
    #expect(PulseSettings.clamp(1, PulseSettings.checkRange) == 5)
    #expect(PulseSettings.clamp(9999, PulseSettings.heartbeatRange) == 600)
    #expect(PulseSettings.int("30") == 30)
    #expect(PulseSettings.int(NSNumber(value: 45)) == 45)
}

@Test func launchdJobReadsTopLevelFields() {
    let printed = """
    system/com.example.agent = {
    \tactive count = 1
    \tstate = running
    \tpid = 412
    \tlast exit code = (never exited)
    \tendpoints = {
    \t\tstate = active
    \t}
    }
    """
    let plist: [String: Any] = ["KeepAlive": true, "ProgramArguments": ["/usr/local/bin/tool", "run"]]
    let job = LaunchdJob.make(label: "com.example.agent", title: "Agent", plist: plist, printed: printed)
    #expect(job.state == "Running")
    #expect(job.pid == 412)
    #expect(job.lastExitCode == "Never exited")
    #expect(job.schedule == "Always running, restarted if it exits")
    #expect(job.program == "/usr/local/bin/tool")
    #expect(job.arguments == ["run"])
    #expect(job.keepAlive == "Yes, restarted whenever it exits")
    #expect(job.user == "root")
    #expect(!job.runAtLoad)
    #expect(LaunchdJob.make(label: "x", title: "x", plist: nil, printed: nil).state == "Not installed")
    #expect(LaunchdJob.make(label: "x", title: "x", plist: plist, printed: nil).state == "Not loaded")
    #expect(LaunchdJob.schedule(["MachServices": ["x": true]]) == "On demand, when the app connects")
}
