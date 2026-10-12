import Foundation

/// Names and paths shared by the agent, the app and the helper. Renaming the tool is a
/// change here, in the Makefile and in the packaging files, and nowhere else.
public enum PulseConstants {
    /// The CFPreferences domain every setting is read from, so a configuration profile
    /// for this domain manages the agent.
    public static let domain = "com.github.computerpulse"
    public static let agentLabel = "com.github.computerpulse"
    public static let helperLabel = "com.github.computerpulse.helper"
    public static let helperPlistName = "com.github.computerpulse.helper.plist"

    public static let appName = "Managed Presence Beacon"
    public static let cliName = "managedpulse"
    public static let appPath = "/Applications/Utilities/Managed Presence Beacon.app"
    public static let cliPath = appPath + "/Contents/MacOS/managedpulse"

    public static let dataDirectory = "/Library/Managed Pulse"
    public static let logDirectory = dataDirectory + "/logs"
    public static let logPath = logDirectory + "/managedpulse.log"
    /// The last send, written by the agent for the app's Run tab.
    public static let lastSendPath = dataDirectory + "/last-send.json"

    public static let documentationURL = URL(string: "https://github.com/emilycarru-its-infra/pulse/tree/main/products/computers/agents/mac")!
    public static let issuesURL = URL(string: "https://github.com/emilycarru-its-infra/pulse/issues")!

    public static var version: String { BuildInfo.version() }
}
