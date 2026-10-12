//
//  Command output, colour-coded by level, monospaced, following the newest line.
//

import SwiftUI

struct ConsoleView: View {
    let lines: [XPCClient.OutputLine]

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 1) {
                    ForEach(lines) { line in
                        Text(line.text)
                            .font(.system(.caption, design: .monospaced))
                            .foregroundStyle(color(line.level))
                            .textSelection(.enabled)
                            .id(line.id)
                    }
                }
                .padding(8)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .background(.black.opacity(0.85))
            .clipShape(RoundedRectangle(cornerRadius: 6))
            .overlay {
                if lines.isEmpty {
                    // The pane is always dark, so the hint is light in both appearances.
                    Text("Send Now sends one heartbeat and shows what happened here.")
                        .foregroundStyle(.white.opacity(0.75))
                }
            }
            .onChange(of: lines.count) {
                if let last = lines.last { proxy.scrollTo(last.id, anchor: .bottom) }
            }
        }
    }

    private func color(_ level: XPCClient.OutputLine.Level) -> Color {
        switch level {
        case .error: .red
        case .warning: .orange
        case .success: .green
        case .debug: .gray
        case .info: .white
        }
    }
}
