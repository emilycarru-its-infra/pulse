//
//  Managed Presence Beacon: the Prefs / Run / Logs window for the managedpresencebeacon agent.
//

import AppKit
import SwiftUI
import PulseAgentCore

enum ContentTab: String, CaseIterable, Identifiable {
    case prefs = "Prefs", run = "Run", logs = "Logs"
    var id: String { rawValue }
    var shortcut: KeyEquivalent {
        switch self { case .prefs: "1"; case .run: "2"; case .logs: "3" }
    }
}

/// Window-wide state the menu commands act on.
@Observable
@MainActor
final class AppModel {
    var tab: ContentTab {
        didSet { UserDefaults.standard.set(tab.rawValue, forKey: "selectedTab") }
    }
    /// Bumped by Find to put the cursor in the log filter.
    var focusFilter = 0

    init() {
        tab = ContentTab(rawValue: UserDefaults.standard.string(forKey: "selectedTab") ?? "") ?? .prefs
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
}

@main
struct ManagedPresenceBeaconApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var delegate
    @State private var model = AppModel()
    @State private var xpc = XPCClient()
    @State private var live = LiveState()

    var body: some Scene {
        Window(PulseConstants.appName, id: "main") {
            ContentView()
                .environment(model)
                .environment(xpc)
                .environment(live)
                .frame(minWidth: 700, minHeight: 500)
        }
        .windowResizability(.contentSize)
        .defaultSize(width: 850, height: 748)
        .commands {
            CommandGroup(replacing: .newItem) {}
            CommandGroup(after: .toolbar) {
                ForEach(ContentTab.allCases) { tab in
                    Button(tab.rawValue) { model.tab = tab }
                        .keyboardShortcut(tab.shortcut, modifiers: .command)
                }
                Divider()
            }
            CommandMenu("Beacon") {
                Button("Send Now") { sendNow() }
                    .keyboardShortcut("r", modifiers: .command)
                    .disabled(xpc.isRunning || xpc.helperStatus != .registered)
                Button("Refresh") { live.refresh() }
                    .keyboardShortcut("r", modifiers: [.command, .shift])
                Divider()
                Button("Reveal Log in Finder") { Self.revealLog() }
                    .keyboardShortcut("r", modifiers: [.command, .option])
            }
            CommandGroup(after: .textEditing) {
                Button("Filter Log…") {
                    model.tab = .logs
                    model.focusFilter += 1
                }
                .keyboardShortcut("f", modifiers: .command)
            }
            CommandGroup(replacing: .help) {
                Button("\(PulseConstants.appName) Help") { NSWorkspace.shared.open(PulseConstants.documentationURL) }
                Button("Report an Issue") { NSWorkspace.shared.open(PulseConstants.issuesURL) }
            }
        }
    }

    @MainActor private func sendNow() {
        model.tab = .run
        xpc.run(["send", "--verbose"])
    }

    static func revealLog() {
        let url = URL(fileURLWithPath: PulseConstants.logPath)
        if FileManager.default.fileExists(atPath: url.path) {
            NSWorkspace.shared.activateFileViewerSelecting([url])
        } else {
            NSWorkspace.shared.open(URL(fileURLWithPath: PulseConstants.dataDirectory))
        }
    }
}
