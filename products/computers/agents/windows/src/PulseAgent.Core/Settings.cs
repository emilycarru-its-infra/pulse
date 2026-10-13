using System.Security.AccessControl;
using System.Security.Principal;
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

    /// <summary>An optional shared key sent as X-Pulse-Key, for a pilot without device certificates.
    /// It lives only in the protected Secrets key: every other key, and policy, is readable by any user.</summary>
    public string? IngestKey { get; init; }

    public int CheckIntervalSeconds { get; init; } = DefaultCheckSeconds;
    public int HeartbeatIntervalSeconds { get; init; } = DefaultHeartbeatSeconds;

    /// <summary>Present the device's Entra certificate as the TLS client certificate.</summary>
    public bool UseDeviceCertificate { get; init; } = true;

    public bool VerboseLogging { get; init; }
}

/// <summary>Reads and writes the settings: machine values under HKLM\SOFTWARE\&lt;product&gt;,
/// policy values (Intune or Group Policy) under HKLM\SOFTWARE\Policies\&lt;product&gt;, and the shared
/// key under HKLM\SOFTWARE\&lt;product&gt;\Secrets, which only SYSTEM and Administrators can read.</summary>
public static class SettingsStore
{
    public const string IngestUrl = nameof(AgentSettings.IngestUrl);
    public const string IngestKey = nameof(AgentSettings.IngestKey);
    public const string CheckIntervalSeconds = nameof(AgentSettings.CheckIntervalSeconds);
    public const string HeartbeatIntervalSeconds = nameof(AgentSettings.HeartbeatIntervalSeconds);
    public const string UseDeviceCertificate = nameof(AgentSettings.UseDeviceCertificate);
    public const string VerboseLogging = nameof(AgentSettings.VerboseLogging);

    /// <summary>The settings policy may manage. The shared key is not one: policy is readable on the device.</summary>
    public static readonly string[] Keys =
        [IngestUrl, CheckIntervalSeconds, HeartbeatIntervalSeconds, UseDeviceCertificate, VerboseLogging];

    /// <summary>The effective settings, from the registry. Unelevated, the shared key reads as unset.</summary>
    public static AgentSettings Load() => Resolve(
        key => Read(Identity.PolicyKey, key), key => Read(Identity.SettingsKey, key), key => Read(Identity.SecretsKey, key));

    /// <summary>The keys policy sets on this device.</summary>
    public static HashSet<string> ManagedKeys() =>
        Keys.Where(k => Read(Identity.PolicyKey, k) is not null).ToHashSet(StringComparer.OrdinalIgnoreCase);

    /// <summary>The effective settings from the policy, machine and secrets lookups, each returning
    /// the raw registry value or null. The shared key comes from the secrets lookup alone.</summary>
    public static AgentSettings Resolve(Func<string, object?> policy, Func<string, object?> machine, Func<string, object?>? secrets = null)
    {
        object? Get(string key) => policy(key) ?? machine(key);
        var defaults = new AgentSettings();
        var check = Clamp(AsInt(Get(CheckIntervalSeconds)) ?? defaults.CheckIntervalSeconds, 5, 300);
        var heartbeat = Clamp(AsInt(Get(HeartbeatIntervalSeconds)) ?? defaults.HeartbeatIntervalSeconds, 15, 3600);
        return new AgentSettings
        {
            IngestUrl = AsString(Get(IngestUrl)),
            IngestKey = AsString(secrets?.Invoke(IngestKey)),
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
        var values = new Dictionary<string, object>
        {
            [IngestUrl] = settings.IngestUrl ?? "",
            [CheckIntervalSeconds] = settings.CheckIntervalSeconds,
            [HeartbeatIntervalSeconds] = settings.HeartbeatIntervalSeconds,
            [UseDeviceCertificate] = settings.UseDeviceCertificate,
            [VerboseLogging] = settings.VerboseLogging,
        };
        if (!string.IsNullOrWhiteSpace(settings.IngestKey)) values[IngestKey] = settings.IngestKey;
        SaveValues(values.Where(v => !managed.Contains(v.Key)).ToDictionary());
    }

    /// <summary>Writes just the given keys: strings as text, ints and bools as DWORDs, and the
    /// ingest key to the Secrets key. The caller has already left out any key policy manages.</summary>
    public static void SaveValues(IReadOnlyDictionary<string, object> values)
    {
        using var key = RegistryKey.OpenBaseKey(RegistryHive.LocalMachine, RegistryView.Registry64)
            .CreateSubKey(Identity.SettingsKey, writable: true);
        foreach (var (name, value) in values)
        {
            if (name == IngestKey) SaveSecret(IngestKey, (string)value);
            else if (value is bool flag) key.SetValue(name, flag ? 1 : 0, RegistryValueKind.DWord);
            else if (value is int number) key.SetValue(name, number, RegistryValueKind.DWord);
            else key.SetValue(name, value.ToString() ?? "", RegistryValueKind.String);
        }
    }

    /// <summary>Writes a credential to the Secrets key, which keeps only SYSTEM and Administrators
    /// and inherits nothing.</summary>
    private static void SaveSecret(string name, string value)
    {
        var security = new RegistrySecurity();
        security.SetAccessRuleProtection(isProtected: true, preserveInheritance: false);
        foreach (var sid in new[] { WellKnownSidType.LocalSystemSid, WellKnownSidType.BuiltinAdministratorsSid })
        {
            security.AddAccessRule(new RegistryAccessRule(new SecurityIdentifier(sid, null),
                RegistryRights.FullControl, InheritanceFlags.ContainerInherit, PropagationFlags.None, AccessControlType.Allow));
        }
        using var root = RegistryKey.OpenBaseKey(RegistryHive.LocalMachine, RegistryView.Registry64);
        using var key = root.CreateSubKey(Identity.SecretsKey, writable: true);
        key.SetAccessControl(security);
        key.SetValue(name, value, RegistryValueKind.String);
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
