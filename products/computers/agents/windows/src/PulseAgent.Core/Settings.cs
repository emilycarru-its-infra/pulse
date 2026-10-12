using Microsoft.Win32;

namespace PulseAgent.Core;

/// <summary>What the agent needs to know. Policy wins over the machine settings, which win
/// over the defaults.</summary>
public sealed record AgentSettings
{
    public const int DefaultCheckSeconds = 15;
    public const int DefaultHeartbeatSeconds = 60;

    /// <summary>Where events go: the product's POST /api/ingest address.</summary>
    public string? IngestUrl { get; init; }

    /// <summary>An optional shared key sent as X-Pulse-Key, for a pilot without device certificates.</summary>
    public string? IngestKey { get; init; }

    public int CheckIntervalSeconds { get; init; } = DefaultCheckSeconds;
    public int HeartbeatIntervalSeconds { get; init; } = DefaultHeartbeatSeconds;

    /// <summary>Present the device's Entra certificate as the TLS client certificate.</summary>
    public bool UseDeviceCertificate { get; init; } = true;

    public bool VerboseLogging { get; init; }
}

/// <summary>Reads and writes the settings: machine values under HKLM\SOFTWARE\&lt;product&gt;,
/// policy values (Intune or Group Policy) under HKLM\SOFTWARE\Policies\&lt;product&gt;.</summary>
public static class SettingsStore
{
    public const string IngestUrl = nameof(AgentSettings.IngestUrl);
    public const string IngestKey = nameof(AgentSettings.IngestKey);
    public const string CheckIntervalSeconds = nameof(AgentSettings.CheckIntervalSeconds);
    public const string HeartbeatIntervalSeconds = nameof(AgentSettings.HeartbeatIntervalSeconds);
    public const string UseDeviceCertificate = nameof(AgentSettings.UseDeviceCertificate);
    public const string VerboseLogging = nameof(AgentSettings.VerboseLogging);

    public static readonly string[] Keys =
        [IngestUrl, IngestKey, CheckIntervalSeconds, HeartbeatIntervalSeconds, UseDeviceCertificate, VerboseLogging];

    /// <summary>The effective settings, from the registry.</summary>
    public static AgentSettings Load() => Resolve(key => Read(Identity.PolicyKey, key), key => Read(Identity.SettingsKey, key));

    /// <summary>The keys policy sets on this device.</summary>
    public static HashSet<string> ManagedKeys() =>
        Keys.Where(k => Read(Identity.PolicyKey, k) is not null).ToHashSet(StringComparer.OrdinalIgnoreCase);

    /// <summary>The effective settings from a policy lookup and a machine lookup, each returning
    /// the raw registry value or null.</summary>
    public static AgentSettings Resolve(Func<string, object?> policy, Func<string, object?> machine)
    {
        object? Get(string key) => policy(key) ?? machine(key);
        var defaults = new AgentSettings();
        var check = Clamp(AsInt(Get(CheckIntervalSeconds)) ?? defaults.CheckIntervalSeconds, 5, 300);
        var heartbeat = Clamp(AsInt(Get(HeartbeatIntervalSeconds)) ?? defaults.HeartbeatIntervalSeconds, 15, 3600);
        return new AgentSettings
        {
            IngestUrl = AsString(Get(IngestUrl)),
            IngestKey = AsString(Get(IngestKey)),
            CheckIntervalSeconds = check,
            HeartbeatIntervalSeconds = Math.Max(heartbeat, check),
            UseDeviceCertificate = AsBool(Get(UseDeviceCertificate)) ?? defaults.UseDeviceCertificate,
            VerboseLogging = AsBool(Get(VerboseLogging)) ?? defaults.VerboseLogging,
        };
    }

    /// <summary>Writes the machine settings, skipping any key policy manages. An empty ingest key
    /// leaves the saved one in place: a secret is replaced, never shown or cleared by accident.</summary>
    public static void Save(AgentSettings settings, IReadOnlySet<string> managed)
    {
        using var key = RegistryKey.OpenBaseKey(RegistryHive.LocalMachine, RegistryView.Registry64)
            .CreateSubKey(Identity.SettingsKey, writable: true);
        void Put(string name, object value, RegistryValueKind kind)
        {
            if (!managed.Contains(name)) key.SetValue(name, value, kind);
        }
        Put(IngestUrl, settings.IngestUrl ?? "", RegistryValueKind.String);
        if (!string.IsNullOrWhiteSpace(settings.IngestKey)) Put(IngestKey, settings.IngestKey, RegistryValueKind.String);
        Put(CheckIntervalSeconds, settings.CheckIntervalSeconds, RegistryValueKind.DWord);
        Put(HeartbeatIntervalSeconds, settings.HeartbeatIntervalSeconds, RegistryValueKind.DWord);
        Put(UseDeviceCertificate, settings.UseDeviceCertificate ? 1 : 0, RegistryValueKind.DWord);
        Put(VerboseLogging, settings.VerboseLogging ? 1 : 0, RegistryValueKind.DWord);
    }

    private static object? Read(string path, string name)
    {
        try
        {
            // 64-bit view only: Intune and Group Policy write there, and a stale WOW6432Node copy
            // must never outrank it.
            using var root = RegistryKey.OpenBaseKey(RegistryHive.LocalMachine, RegistryView.Registry64);
            using var key = root.OpenSubKey(path);
            return key?.GetValue(name);
        }
        catch
        {
            return null;
        }
    }

    private static int Clamp(int value, int min, int max) => Math.Min(max, Math.Max(min, value));

    internal static string? AsString(object? value) =>
        value?.ToString()?.Trim() is { Length: > 0 } s ? s : null;

    internal static int? AsInt(object? value) => value switch
    {
        int i => i,
        long l => (int)l,
        string s when int.TryParse(s.Trim(), out var i) => i,
        _ => null,
    };

    internal static bool? AsBool(object? value) => value switch
    {
        int i => i != 0,
        long l => l != 0,
        string s when bool.TryParse(s.Trim(), out var b) => b,
        string s when int.TryParse(s.Trim(), out var i) => i != 0,
        _ => null,
    };
}
