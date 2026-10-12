//
//  The window: Prefs, Run and Logs. A plain TabView, which macOS 26 draws as the
//  Liquid Glass segmented control in the title bar.
//

import SwiftUI

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
        .onAppear {
            xpc.checkHelperStatus()
            xpc.connect()
        }
    }
}
