//
//  The window: Prefs, Run and Logs. A plain TabView, which macOS 26 draws as the
//  Liquid Glass segmented control in the toolbar, with no title text, and the version
//  in a footer under every tab.
//

import SwiftUI
import PulseAgentCore

struct ContentView: View {
    @Environment(AppModel.self) private var model
    @Environment(XPCClient.self) private var xpc
    @State private var settings = SettingsViewModel()

    var body: some View {
        @Bindable var model = model
        TabView(selection: $model.tab) {
            SettingsView(viewModel: settings)
                .tabItem { Text(ContentTab.prefs.rawValue) }
                .tag(ContentTab.prefs)
            RunView()
                .tabItem { Text(ContentTab.run.rawValue) }
                .tag(ContentTab.run)
            LogView()
                .tabItem { Text(ContentTab.logs.rawValue) }
                .tag(ContentTab.logs)
        }
        .safeAreaInset(edge: .bottom, spacing: 0) { footer }
        .hidingWindowTitle()
        .onAppear {
            xpc.checkHelperStatus()
            xpc.connect()
        }
    }
}

private extension ContentView {
    var version: String {
        let short = Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String
        let build = Bundle.main.infoDictionary?["CFBundleVersion"] as? String
        guard let short else { return PulseConstants.version }
        return build.map { "Version \(short) (\($0))" } ?? "Version \(short)"
    }

    var footer: some View {
        VStack(spacing: 0) {
            Divider()
            Text(version)
                .font(.caption)
                .foregroundStyle(.secondary)
                .textSelection(.enabled)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 6)
        }
        .background(.bar)
    }
}

private extension View {
    /// Prefs, Run and Logs sit in the toolbar with no title text beside them.
    @ViewBuilder func hidingWindowTitle() -> some View {
        if #available(macOS 15.0, *) {
            toolbar(removing: .title)
        } else {
            self
        }
    }
}
