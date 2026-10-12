//
//  Run: what this Mac would report right now, the last send, and Send Now with its
//  output.
//

import SwiftUI
import PulseAgentCore

struct RunView: View {
    @Environment(XPCClient.self) private var xpc
    @Environment(LiveState.self) private var live
    @State private var showDebug = false

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            controls
            HStack(alignment: .top, spacing: 20) {
                nowCard.frame(maxWidth: .infinity, alignment: .top)
                lastSendCard.frame(maxWidth: .infinity, alignment: .top)
            }
            ConsoleView(lines: showDebug ? xpc.outputLines : xpc.outputLines.filter { $0.level != .debug })
        }
        .padding(20)
        .onAppear { live.start() }
        .onDisappear { live.stop() }
    }

    private var controls: some View {
        HStack(spacing: 12) {
            sendButton
            if xpc.isRunning {
                ProgressView().controlSize(.small)
                Text("Sending…").foregroundStyle(.secondary)
            } else if let code = xpc.lastExitCode {
                Label(code == 0 ? "Sent" : "Failed (exit \(code))",
                      systemImage: code == 0 ? "checkmark.circle.fill" : "xmark.circle.fill")
                    .foregroundStyle(code == 0 ? .green : .red)
            }
            Spacer()
            if xpc.helperStatus != .registered {
                Label("Helper: \(xpc.helperStatus.rawValue)", systemImage: "exclamationmark.triangle.fill")
                    .foregroundStyle(.orange)
                    .font(.caption)
            }
            Toggle("Debug", isOn: $showDebug)
                .toggleStyle(.checkbox)
                .help("Show or hide debug lines")
            if !xpc.outputLines.isEmpty {
                Button("Clear") { xpc.outputLines.removeAll(); xpc.lastExitCode = nil }
                    .controlSize(.small)
            }
        }
    }

    @ViewBuilder private var sendButton: some View {
        let button = Button { xpc.run(["send", "--verbose"]) } label: {
            Label("Send Now", systemImage: "dot.radiowaves.left.and.right")
        }
        .controlSize(.large)
        .disabled(xpc.isRunning || xpc.helperStatus != .registered)
        .help(xpc.helperStatus == .registered ? "Send one heartbeat now (⌘R)" : "Needs the helper, which the installer sets up")
        #if compiler(>=6.2)
        if #available(macOS 26, *) {
            button.buttonStyle(.glassProminent)
        } else {
            button.buttonStyle(.borderedProminent)
        }
        #else
        button.buttonStyle(.borderedProminent)
        #endif
    }

    private var nowCard: some View {
        GroupBox {
            Grid(alignment: .leading, horizontalSpacing: 14, verticalSpacing: 6) {
                fact("Device", "\(live.hostname) · \(live.serial)")
                fact("Signed in", live.snapshot.active ? "Yes" : "No")
                fact("Screen locked", live.snapshot.locked ? "Yes" : "No")
                fact("Idle", Duration.seconds(live.snapshot.idleSeconds).formatted(.units(allowed: [.hours, .minutes, .seconds], width: .abbreviated)))
                GridRow {
                    Text("Seat shows as").foregroundStyle(.secondary)
                    Label(seatWord, systemImage: "circle.fill")
                        .foregroundStyle(seatColor)
                }
            }
            .padding(.vertical, 6)
            .frame(maxWidth: .infinity, alignment: .leading)
        } label: {
            Label("Right now", systemImage: "desktopcomputer").font(.headline)
        }
    }

    private var lastSendCard: some View {
        GroupBox {
            Grid(alignment: .leading, horizontalSpacing: 14, verticalSpacing: 6) {
                if let last = live.lastSend {
                    fact("When", last.at)
                    fact("Event", last.type)
                    fact("Result", last.ok ? "HTTP \(last.status ?? 0)" : (last.error ?? "Failed"))
                    fact("Certificate", last.identity ?? "Not asked for")
                } else {
                    GridRow { Text("Nothing sent yet").foregroundStyle(.secondary) }
                }
            }
            .padding(.vertical, 6)
            .frame(maxWidth: .infinity, alignment: .leading)
        } label: {
            Label("Last send", systemImage: "paperplane").font(.headline)
        }
    }

    private func fact(_ name: String, _ value: String) -> some View {
        GridRow {
            Text(name).foregroundStyle(.secondary)
            Text(value).textSelection(.enabled)
        }
    }

    private var seatWord: String {
        switch live.snapshot.seatState {
        case "in_use": "In use"
        case "possibly_free": "Possibly free"
        default: "Free"
        }
    }

    private var seatColor: Color {
        switch live.snapshot.seatState {
        case "in_use": .primary
        case "possibly_free": .orange
        default: .green
        }
    }
}
