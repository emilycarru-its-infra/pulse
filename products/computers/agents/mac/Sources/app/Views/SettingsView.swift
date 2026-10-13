//
//  Prefs: the app header with Unlock, then two columns of cards and the Services card.
//  Every field is read-only until an administrator unlocks the window. A value a
//  configuration profile sets stays gray either way, under one banner that says so.
//

import SwiftUI
import PulseAgentCore

struct SettingsView: View {
    @Bindable var viewModel: SettingsViewModel
    @Environment(XPCClient.self) private var xpc
    @State private var revealKey = false

    private var locked: Bool { !xpc.isUnlocked }

    var body: some View {
        ScrollView {
            VStack(spacing: 16) {
                header
                Divider()
                if viewModel.anyManaged { profileBanner }
                HStack(alignment: .top, spacing: 20) {
                    VStack(spacing: 16) {
                        connectionCard
                    }
                    .frame(maxWidth: .infinity, alignment: .top)
                    VStack(spacing: 16) {
                        timingCard
                    }
                    .frame(maxWidth: .infinity, alignment: .top)
                }
                servicesCard
                saveStatus
            }
            .padding()
        }
        .onAppear {
            viewModel.configure(client: xpc)
            viewModel.load()
        }
    }

    private var header: some View {
        VStack(spacing: 8) {
            Image(nsImage: NSApp.applicationIconImage)
                .resizable()
                .aspectRatio(contentMode: .fit)
                .frame(width: 72, height: 72)
                .accessibilityHidden(true)
            Text(PulseConstants.appName)
                .font(.largeTitle.bold())
            Text("Tells Pulse whether this computer is free, without saying who is using it.")
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
            HStack(spacing: 16) {
                Link("Documentation", destination: PulseConstants.documentationURL)
                Link("Report Issue", destination: PulseConstants.issuesURL)
            }
            .font(.caption)
            lockButton
                .padding(.top, 4)
        }
        .padding(.top, 8)
    }

    @ViewBuilder private var lockButton: some View {
        if locked {
            Button {
                if xpc.unlock() { viewModel.load() }
            } label: {
                Label("Unlock to make changes", systemImage: "lock.fill")
            }
            .help("An administrator must authenticate before the beacon's settings can change")
        } else {
            Button {
                xpc.lock()
            } label: {
                Label("Lock", systemImage: "lock.open.fill")
            }
            .help("Stop making changes")
        }
    }

    /// One line for every key a profile sets, worded as System Settings words it.
    private var profileBanner: some View {
        Label("Settings shown in gray have been configured by a profile.", systemImage: "lock.fill")
            .font(.callout)
            .foregroundStyle(.secondary)
            .frame(maxWidth: .infinity, alignment: .leading)
    }

    @ViewBuilder private var saveStatus: some View {
        Group {
            switch viewModel.saveStatus {
            case .idle: EmptyView()
            case .saving:
                HStack(spacing: 6) {
                    ProgressView().controlSize(.small)
                    Text("Saving").foregroundStyle(.secondary)
                }
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
                            .foregroundStyle(.secondary)
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

    private var servicesCard: some View {
        GroupBox {
            VStack(alignment: .leading, spacing: 12) {
                ForEach(viewModel.services) { job in
                    serviceRow(job)
                    if job != viewModel.services.last { Divider() }
                }
            }
            .padding(.vertical, 8)
            .frame(maxWidth: .infinity, alignment: .leading)
        } label: {
            Label("Services", systemImage: "gearshape.2").font(.headline)
        }
    }

    private func serviceRow(_ job: LaunchdJob) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(alignment: .firstTextBaseline) {
                Text(job.title).font(.body.weight(.medium))
                Text(job.label)
                    .font(.caption.monospaced())
                    .foregroundStyle(.secondary)
                    .textSelection(.enabled)
                Spacer()
                Label(job.pid.map { "\(job.state), pid \($0)" } ?? job.state, systemImage: stateSymbol(job))
                    .font(.callout)
                    .foregroundStyle(job.state == "Running" ? .green : .secondary)
            }
            Grid(alignment: .leading, horizontalSpacing: 12, verticalSpacing: 2) {
                GridRow {
                    Text("Schedule").foregroundStyle(.secondary)
                    Text(job.schedule)
                }
                GridRow {
                    Text("Last exit code").foregroundStyle(.secondary)
                    Text(job.lastExitCode ?? "—")
                }
                if let program = job.program {
                    GridRow {
                        Text("Runs").foregroundStyle(.secondary)
                        Text(program).textSelection(.enabled).lineLimit(2).truncationMode(.middle)
                    }
                }
            }
            .font(.caption)
        }
        .accessibilityElement(children: .combine)
    }

    private func stateSymbol(_ job: LaunchdJob) -> String {
        switch job.state {
        case "Running": "circle.fill"
        case "Not installed", "Not loaded": "circle.dashed"
        default: "circle"
        }
    }

    /// A field a profile sets stays disabled and gray; the banner above explains why.
    @ViewBuilder
    private func row<Content: View>(_ key: PulseSettings.Key, _ label: String? = nil,
                                     @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            if let label { Text(label).font(.caption).foregroundStyle(.secondary) }
            content().disabled(viewModel.isManaged(key) || locked)
        }
    }
}
