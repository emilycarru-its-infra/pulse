//
//  Prefs: the app header, then two columns of cards and the Services card. A value a
//  configuration profile sets stays gray, under one banner that says so; any other
//  change asks for an administrator when it is saved.
//

import SwiftUI
import PulseAgentCore

struct SettingsView: View {
    @Bindable var viewModel: SettingsViewModel
    @Environment(XPCClient.self) private var xpc
    @State private var expandedServices: Set<String> = []

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
                if !viewModel.services.isEmpty { servicesCard }
                footer
            }
            .padding()
        }
        .onAppear {
            viewModel.configure(client: xpc)
            viewModel.load()
            // Nothing is focused at launch, so the first field shows no focus ring; Tab
            // still reaches every control.
            DispatchQueue.main.async { NSApp.keyWindow?.makeFirstResponder(nil) }
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
        }
        .padding(.top, 8)
    }

    /// The version and the help links on the left, the save state on the right.
    private var footer: some View {
        HStack(spacing: 12) {
            Text("v\(PulseConstants.version)")
                .font(.caption)
                .foregroundStyle(.secondary)
                .textSelection(.enabled)
            Link("Documentation", destination: PulseConstants.documentationURL)
                .font(.caption)
            Link("Report Issue", destination: PulseConstants.issuesURL)
                .font(.caption)
            Spacer()
            saveStatus
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
        .accessibilityElement(children: .combine)
    }

    private var connectionCard: some View {
        GroupBox {
            VStack(alignment: .leading, spacing: 12) {
                row(.ingestURL, "Ingest URL") {
                    TextField("https://status.example.edu/computers/api/ingest", text: $viewModel.ingestURL)
                        .textFieldStyle(.roundedBorder)
                }
                ingestKeyStatus
                VStack(alignment: .leading, spacing: 2) {
                    Text("Device certificate").font(.caption).foregroundStyle(.secondary)
                    if let cert = viewModel.certificate {
                        Label {
                            Text(cert.subject)
                                .font(.body.monospaced())
                                .lineLimit(1)
                                .minimumScaleFactor(0.6)
                                .truncationMode(.middle)
                                .textSelection(.enabled)
                                .help(cert.subject)
                                .padding(.trailing, 12)
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

    /// The ingest key as status only: its value is never read into the window, and only
    /// a configuration profile sets it. The device certificate is the main credential.
    private var ingestKeyStatus: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text("Ingest key").font(.caption).foregroundStyle(.secondary)
            switch viewModel.ingestKeyState {
            case .managed:
                Label("Set by profile", systemImage: "lock.fill")
                    .foregroundStyle(.secondary)
            case .set:
                Text("Set")
            case .notSet:
                Text("Not set").foregroundStyle(.secondary)
            }
            if viewModel.ingestKeyState != .managed {
                Text("Optional shared key, set by a configuration profile for \(PulseConstants.domain).")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .accessibilityElement(children: .combine)
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
            VStack(alignment: .leading, spacing: 0) {
                ForEach(viewModel.services) { job in
                    serviceRow(job)
                    if job != viewModel.services.last { Divider() }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        } label: {
            Label("Services", systemImage: "gearshape.2").font(.headline)
        }
    }

    /// One collapsed row per job: its label, a summary line and its state. Clicking
    /// anywhere on the row, or Space or Return when it has focus, shows the fields
    /// ReportMate collects for the job, all read-only.
    private func serviceRow(_ job: LaunchdJob) -> some View {
        let open = expandedServices.contains(job.id)
        return VStack(alignment: .leading, spacing: 0) {
            Button {
                toggle(job)
            } label: {
                HStack(alignment: .center, spacing: 10) {
                    Image(systemName: "chevron.right")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.secondary)
                        .rotationEffect(.degrees(open ? 90 : 0))
                    VStack(alignment: .leading, spacing: 2) {
                        Text(job.label)
                            .font(.body.monospaced())
                            .lineLimit(1)
                            .truncationMode(.middle)
                        Text(job.summary)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                    }
                    Spacer(minLength: 12)
                    HStack(spacing: 6) {
                        Circle()
                            .fill(stateColor(job))
                            .frame(width: 9, height: 9)
                        Text(job.statusText)
                            .font(.callout)
                            .foregroundStyle(.secondary)
                    }
                }
                .padding(.vertical, 8)
                .padding(.trailing, 6)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .onKeyPress(.return) { toggle(job); return .handled }
            .onKeyPress(.space) { toggle(job); return .handled }
            .accessibilityLabel("\(job.label), \(job.statusText)")
            .accessibilityHint(open ? "Hides the details" : "Shows the details")
            .accessibilityAddTraits(.isButton)

            if open {
                Grid(alignment: .leading, horizontalSpacing: 12, verticalSpacing: 4) {
                    detail("Type", job.kind)
                    detail("Status", job.statusText)
                    detail("Last exit code", job.lastExitCode ?? "—")
                    detail("Program", job.program ?? "—", mono: true)
                    if !job.arguments.isEmpty { detail("Arguments", job.arguments.joined(separator: " "), mono: true) }
                    detail("Runs at load", job.runAtLoad ? "Yes" : "No")
                    detail("Keep alive", job.keepAlive)
                    detail("Schedule", job.startInterval.map { "Every \($0) seconds" } ?? job.schedule)
                    detail("User", job.user)
                    if let out = job.standardOutPath { detail("Standard output", out, mono: true) }
                    if let err = job.standardErrorPath { detail("Standard error", err, mono: true) }
                    detail("Plist", job.plistPath, mono: true)
                }
                .font(.callout)
                .padding(.leading, 24)
                .padding(.bottom, 10)
            }
        }
    }

    private func toggle(_ job: LaunchdJob) {
        withAnimation(.easeInOut(duration: 0.15)) {
            if expandedServices.contains(job.id) { expandedServices.remove(job.id) } else { expandedServices.insert(job.id) }
        }
    }

    @ViewBuilder
    private func detail(_ name: String, _ value: String, mono: Bool = false) -> some View {
        GridRow {
            Text(name).foregroundStyle(.secondary)
            Text(value)
                .font(mono ? .callout.monospaced() : .callout)
                .textSelection(.enabled)
                .lineLimit(2)
                .truncationMode(.middle)
        }
    }

    private func stateColor(_ job: LaunchdJob) -> Color {
        if job.state == "Running" { return .green }
        if let code = job.lastExitCode, Int(code).map({ $0 != 0 }) ?? false { return .red }
        return .secondary
    }

    /// A field a profile sets stays disabled and gray; the banner above explains why.
    @ViewBuilder
    private func row<Content: View>(_ key: PulseSettings.Key, _ label: String? = nil,
                                     @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            if let label { Text(label).font(.caption).foregroundStyle(.secondary) }
            content().disabled(viewModel.isManaged(key))
        }
    }
}
