//
//  Prefs: the app header, then two columns of cards. A value a configuration profile
//  sets shows that value, greyed, with a lock and the word Managed.
//

import SwiftUI
import PulseAgentCore

struct SettingsView: View {
    @Bindable var viewModel: SettingsViewModel
    @Environment(XPCClient.self) private var xpc
    @State private var revealKey = false

    private var version: String {
        let short = Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String
        let build = Bundle.main.infoDictionary?["CFBundleVersion"] as? String
        guard let short else { return PulseConstants.version }
        return build.map { "v\(short) (\($0))" } ?? "v\(short)"
    }

    var body: some View {
        ScrollView {
            VStack(spacing: 16) {
                header
                saveStatus
                HStack(alignment: .top, spacing: 20) {
                    connectionCard.frame(maxWidth: .infinity, alignment: .top)
                    timingCard.frame(maxWidth: .infinity, alignment: .top)
                }
            }
            .padding(24)
        }
        .onAppear {
            viewModel.configure(client: xpc)
            viewModel.load()
        }
    }

    private var header: some View {
        VStack(spacing: 6) {
            Image(nsImage: NSApp.applicationIconImage)
                .resizable()
                .frame(width: 56, height: 56)
                .accessibilityHidden(true)
            Text(PulseConstants.appName).font(.title2.bold())
            Text("Tells Pulse whether this computer is free, without saying who is using it.")
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
            Text(version)
                .font(.caption)
                .foregroundStyle(.tertiary)
                .textSelection(.enabled)
            HStack(spacing: 14) {
                Link("Documentation", destination: PulseConstants.documentationURL)
                Link("Report Issue", destination: PulseConstants.issuesURL)
            }
            .font(.caption)
        }
    }

    @ViewBuilder private var saveStatus: some View {
        Group {
            switch viewModel.saveStatus {
            case .idle: Text(" ")
            case .saving: Label("Saving…", systemImage: "arrow.triangle.2.circlepath")
            case .saved: Label("Saved", systemImage: "checkmark.circle.fill").foregroundStyle(.green)
            case .failed(let why): Label(why, systemImage: "exclamationmark.triangle.fill").foregroundStyle(.red)
            }
        }
        .font(.callout)
        .frame(maxWidth: .infinity, alignment: .trailing)
        .accessibilityElement(children: .combine)
    }

    private var connectionCard: some View {
        GroupBox {
            VStack(alignment: .leading, spacing: 12) {
                row(.ingestURL, "Ingest URL") {
                    TextField("https://status.example.edu/computers/api/ingest", text: $viewModel.ingestURL)
                        .textFieldStyle(.roundedBorder)
                }
                row(.ingestKey, "Ingest key") {
                    HStack(spacing: 6) {
                        Group {
                            if revealKey {
                                TextField(keyPlaceholder, text: $viewModel.ingestKey)
                            } else {
                                SecureField(keyPlaceholder, text: $viewModel.ingestKey)
                            }
                        }
                        .textFieldStyle(.roundedBorder)
                        Image(systemName: revealKey ? "eye.slash" : "eye")
                            .foregroundStyle(.secondary)
                            .help("Hold to show the key you are typing")
                            .gesture(DragGesture(minimumDistance: 0)
                                .onChanged { _ in revealKey = true }
                                .onEnded { _ in revealKey = false })
                            .accessibilityLabel("Show key while held")
                    }
                }
                VStack(alignment: .leading, spacing: 2) {
                    Text("Device certificate").font(.caption).foregroundStyle(.secondary)
                    if let cert = viewModel.certificate {
                        Label {
                            Text(cert.subject).textSelection(.enabled)
                        } icon: {
                            Image(systemName: "checkmark.seal.fill").foregroundStyle(.green)
                        }
                        if let expires = cert.expires {
                            Text("Expires \(expires.formatted(date: .abbreviated, time: .omitted))")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                    } else {
                        Label("No Intune agent certificate in the System keychain", systemImage: "xmark.seal")
                            .foregroundStyle(.orange)
                    }
                }
            }
            .padding(.vertical, 8)
            .frame(maxWidth: .infinity, alignment: .leading)
        } label: {
            Label("Connection", systemImage: "network").font(.headline)
        }
    }

    private var keyPlaceholder: String {
        if viewModel.isManaged(.ingestKey) { return "Set by profile" }
        return viewModel.hasStoredKey ? "Saved; enter a new value to replace" : "Optional shared key"
    }

    private var timingCard: some View {
        GroupBox {
            VStack(alignment: .leading, spacing: 12) {
                row(.checkInterval, "Look at the console every") {
                    number($viewModel.checkInterval, PulseSettings.checkRange, step: 5)
                }
                row(.heartbeatInterval, "Send a heartbeat every") {
                    number($viewModel.heartbeatInterval, PulseSettings.heartbeatRange, step: 15)
                }
                row(.verboseLogging) {
                    Toggle("Log every check, not only sends", isOn: $viewModel.verboseLogging)
                }
            }
            .padding(.vertical, 8)
            .frame(maxWidth: .infinity, alignment: .leading)
        } label: {
            Label("Timing", systemImage: "timer").font(.headline)
        }
    }

    private func number(_ value: Binding<Int>, _ range: ClosedRange<Int>, step: Int) -> some View {
        HStack(spacing: 6) {
            TextField("", value: value, format: .number)
                .textFieldStyle(.roundedBorder)
                .frame(width: 60)
                .multilineTextAlignment(.trailing)
            Stepper("", value: value, in: range, step: step).labelsHidden()
            Text("seconds").foregroundStyle(.secondary)
        }
    }

    @ViewBuilder
    private func row<Content: View>(_ key: PulseSettings.Key, _ label: String? = nil,
                                     @ViewBuilder content: () -> Content) -> some View {
        let managed = viewModel.isManaged(key)
        VStack(alignment: .leading, spacing: 2) {
            if let label { Text(label).font(.caption).foregroundStyle(.secondary) }
            content().disabled(managed)
            if managed {
                Label("Managed", systemImage: "lock.fill")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
    }
}
