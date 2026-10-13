using System.Reflection;

namespace PulseAgent.Core;

/// <summary>
/// Every name the agent is known by. The values are stamped into the assembly from
/// Directory.Build.props, so renaming the product is a change to that one file.
/// </summary>
public static class Identity
{
    private static string Meta(string key, string fallback) =>
        typeof(Identity).Assembly.GetCustomAttributes<AssemblyMetadataAttribute>()
            .FirstOrDefault(a => a.Key == key)?.Value is { Length: > 0 } value ? value : fallback;

    /// <summary>The tool's name: the install folder, registry and policy keys, and scheduled tasks.</summary>
    public static readonly string ProductKey = Meta("PulseProductKey", "PulseAgent");

    /// <summary>The ProgramData folder for data and logs.</summary>
    public static readonly string DataName = Meta("PulseDataName", "PulseAgent");

    /// <summary>The name people see: the window title and the GUI executable.</summary>
    public static readonly string GuiName = Meta("PulseGuiName", "Pulse Agent");

    /// <summary>The command-line executable, without its .exe extension.</summary>
    public static readonly string CliName = Meta("PulseCliName", "pulseagent");

    /// <summary>The per-user idle helper, without its .exe extension.</summary>
    public static readonly string IdleName = Meta("PulseIdleName", "pulseagent-idle");

    /// <summary>The base name of the app icon files.</summary>
    public static readonly string IconName = Meta("PulseIconName", "PulseAgent");

    /// <summary>The build stamp, YYYY.MM.DD.HHMM.</summary>
    public static readonly string Version = Meta("BuildTimestamp", "0.0.0.0");

    public static string SettingsKey => $@"SOFTWARE\{ProductKey}";
    public static string PolicyKey => $@"SOFTWARE\Policies\{ProductKey}";

    /// <summary>The protected key for credentials: SYSTEM and Administrators only, nothing inherited.</summary>
    public static string SecretsKey => $@"SOFTWARE\{ProductKey}\Secrets";

    public static string DataDirectory => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData), DataName);
    public static string LogDirectory => Path.Combine(DataDirectory, "logs");
    public static string IdleDirectory => Path.Combine(DataDirectory, "idle");
    /// <summary>In logs\, the one folder users may read, so the GUI can show it unelevated.</summary>
    public static string StatusFile => Path.Combine(LogDirectory, "status.json");

    public static string AgentTaskName => ProductKey;
    public static string IdleTaskName => $"{ProductKey} Idle";
    public static string ShutdownTaskName => $"{ProductKey} Shutdown";

    /// <summary>The event the GUI's Send now button signals and the agent waits on.</summary>
    public static string SendNowEventName => $@"Global\{ProductKey}.SendNow";

    /// <summary>The version as the window shows it: v2026.10.05 (1342).</summary>
    public static string VersionDisplay => FormatVersion(Version);

    internal static string FormatVersion(string stamp)
    {
        var parts = stamp.Split('.');
        return parts.Length == 4 ? $"v{parts[0]}.{parts[1]}.{parts[2]} ({parts[3]})" : $"v{stamp}";
    }
}
