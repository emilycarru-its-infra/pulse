//
//  Logs: the agent's log, followed live, with a filter. ⌘F focuses the filter.
//

import SwiftUI
import PulseAgentCore

struct LogView: View {
    @Environment(AppModel.self) private var model
    @State private var lines: [String] = []
    @State private var filter = ""
    @State private var follow = true
    @State private var modified: Date?
    @FocusState private var filterFocused: Bool

    private static let keep = 5000

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 8) {
                Image(systemName: "line.3.horizontal.decrease").foregroundStyle(.secondary)
                TextField("Filter", text: $filter)
                    .textFieldStyle(.roundedBorder)
                    .focused($filterFocused)
                Toggle("Follow", isOn: $follow)
                    .toggleStyle(.checkbox)
                    .help("Keep the newest line in view")
                Button { ManagedPresenceBeaconApp.revealLog() } label: { Image(systemName: "folder") }
                    .buttonStyle(.borderless)
                    .help("Reveal the log in Finder (⌥⌘R)")
                    .accessibilityLabel("Reveal the log in Finder")
                Button { NSWorkspace.shared.open(URL(fileURLWithPath: PulseConstants.logPath)) } label: {
                    Image(systemName: "arrow.up.forward.square")
                }
                .buttonStyle(.borderless)
                .help("Open the log in its default app")
                .accessibilityLabel("Open the log")
            }
            .padding(.horizontal, 16)
            .frame(minHeight: 40)
            Divider()
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 1) {
                        ForEach(Array(shown.enumerated()), id: \.offset) { i, line in
                            Text(line)
                                .font(.system(.caption, design: .monospaced))
                                .foregroundStyle(color(line))
                                .textSelection(.enabled)
                                .id(i)
                        }
                    }
                    .padding(8)
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
                .background(.black.opacity(0.85))
                .overlay {
                    if lines.isEmpty {
                        ContentUnavailableView("No Log Yet", systemImage: "doc.text",
                                               description: Text("The agent writes to \(PulseConstants.logPath)."))
                            .foregroundStyle(.white.opacity(0.8))
                            .environment(\.colorScheme, .dark)
                    }
                }
                .onChange(of: shown.count) {
                    if follow, shown.count > 0 { proxy.scrollTo(shown.count - 1, anchor: .bottom) }
                }
            }
        }
        .task {
            while !Task.isCancelled {
                reload()
                try? await Task.sleep(for: .seconds(1))
            }
        }
        .onChange(of: model.focusFilter) { filterFocused = true }
        .onAppear { if model.focusFilter > 0 { filterFocused = true } }
    }

    private var shown: [String] {
        filter.isEmpty ? lines : lines.filter { $0.localizedCaseInsensitiveContains(filter) }
    }

    private func reload() {
        let path = PulseConstants.logPath
        let date = (try? FileManager.default.attributesOfItem(atPath: path))?[.modificationDate] as? Date
        guard date != modified else { return }
        modified = date
        let text = (try? String(contentsOfFile: path, encoding: .utf8)) ?? ""
        lines = Array(text.split(separator: "\n", omittingEmptySubsequences: true).suffix(Self.keep).map(String.init))
    }

    private func color(_ line: String) -> Color {
        if line.contains("] ERROR") { return .red }
        if line.contains("] WARN") { return .orange }
        if line.contains("] DEBUG") { return .gray }
        if line.contains("] INFO  Sent") { return .green }
        return .white
    }
}
