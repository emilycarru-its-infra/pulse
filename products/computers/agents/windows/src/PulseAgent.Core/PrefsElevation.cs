using System.ComponentModel;
using System.Diagnostics;
using System.Security.Principal;
using System.Text;
using System.Text.Json;

namespace PulseAgent.Core;

/// <summary>
/// How the GUI saves settings without running elevated. Settings live in HKLM, so a change made
/// in an unelevated GUI is handed to a copy of the app started through UAC in a hidden apply mode,
/// with only the changed keys as base64 JSON on its command line. That copy checks every key
/// itself, writes HKLM and exits; it never shows a window. No service and no file sits between them.
/// </summary>
public static class PrefsElevation
{
    /// <summary>Command-line switch for the hidden apply mode; the payload follows it.</summary>
    public const string ApplyArgument = "--apply-settings";

    /// <summary>Win32 ERROR_CANCELLED: the user dismissed the UAC prompt.</summary>
    public const int ErrorCancelled = 1223;

    /// <summary>Exit codes of the apply mode.</summary>
    public const int Applied = 0;
    public const int WriteFailed = 1;
    public const int Refused = 2;

    public static bool IsElevationCancelled(Exception? ex)
        => ex is Win32Exception { NativeErrorCode: ErrorCancelled };

    /// <summary>Whether this process holds an elevated administrator token.</summary>
    public static bool IsProcessElevated()
    {
        try
        {
            using var identity = WindowsIdentity.GetCurrent();
            return new WindowsPrincipal(identity).IsInRole(WindowsBuiltInRole.Administrator);
        }
        catch
        {
            return false;
        }
    }

    /// <summary>The changed keys as the apply mode's payload. Values are strings, ints or bools.</summary>
    public static string Encode(IReadOnlyDictionary<string, object> changes)
        => Convert.ToBase64String(Encoding.UTF8.GetBytes(JsonSerializer.Serialize(changes)));

    /// <summary>Start info that runs <paramref name="exePath"/> elevated in the apply mode.</summary>
    public static ProcessStartInfo BuildElevatedApply(string exePath, IReadOnlyDictionary<string, object> changes)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(exePath);
        return new ProcessStartInfo
        {
            FileName = exePath,
            Arguments = $"{ApplyArgument} {Encode(changes)}",
            UseShellExecute = true,
            Verb = "runas",
            WindowStyle = ProcessWindowStyle.Hidden,
            WorkingDirectory = Path.GetDirectoryName(exePath) ?? string.Empty,
        };
    }

    /// <summary>The payload when <paramref name="args"/> asks for the apply mode, else null.
    /// An apply switch with nothing after it gives an empty payload, which Validate refuses.</summary>
    public static string? ApplyPayload(IReadOnlyList<string> args)
    {
        for (var i = 0; i < args.Count; i++)
        {
            if (string.Equals(args[i]?.Trim(), ApplyArgument, StringComparison.OrdinalIgnoreCase))
                return i + 1 < args.Count ? args[i + 1] : "";
        }
        return null;
    }

    /// <summary>
    /// Decodes and checks a payload as the save code would: only known keys, never one policy
    /// manages, each of the right type, intervals clamped to their ranges. Returns the values to
    /// write, or null with the reason.
    /// </summary>
    public static Dictionary<string, object>? Validate(string payload, IReadOnlySet<string> managed, out string error)
    {
        error = "";
        Dictionary<string, JsonElement>? raw;
        try
        {
            raw = JsonSerializer.Deserialize<Dictionary<string, JsonElement>>(Convert.FromBase64String(payload));
        }
        catch (Exception ex) when (ex is FormatException or JsonException)
        {
            error = "The settings could not be read.";
            return null;
        }
        if (raw is null || raw.Count == 0)
        {
            error = "No settings were given.";
            return null;
        }

        var values = new Dictionary<string, object>(StringComparer.OrdinalIgnoreCase);
        foreach (var (name, value) in raw)
        {
            var key = SettingsStore.Keys.Append(SettingsStore.IngestKey)
                .FirstOrDefault(k => string.Equals(k, name, StringComparison.OrdinalIgnoreCase));
            if (key is null)
            {
                error = $"{name} is not a setting.";
                return null;
            }
            if (managed.Contains(key))
            {
                error = $"{key} is set by policy.";
                return null;
            }
            object? parsed = key switch
            {
                SettingsStore.IngestUrl when value.ValueKind == JsonValueKind.String => value.GetString()!.Trim(),
                SettingsStore.IngestKey when value.ValueKind == JsonValueKind.String && value.GetString()!.Length > 0 => value.GetString()!,
                SettingsStore.CheckIntervalSeconds when value.ValueKind == JsonValueKind.Number && value.TryGetInt32(out var check) => Math.Clamp(check, 5, 300),
                SettingsStore.HeartbeatIntervalSeconds when value.ValueKind == JsonValueKind.Number && value.TryGetInt32(out var beat) => Math.Clamp(beat, 15, 3600),
                SettingsStore.UseDeviceCertificate or SettingsStore.VerboseLogging
                    when value.ValueKind is JsonValueKind.True or JsonValueKind.False => value.GetBoolean(),
                _ => null,
            };
            if (parsed is null)
            {
                error = $"{key} has a value of the wrong kind.";
                return null;
            }
            values[key] = parsed;
        }
        return values;
    }

    /// <summary>The apply mode itself: checks the payload against the policy on this device,
    /// writes HKLM and returns the exit code.</summary>
    public static int Apply(string payload)
    {
        var values = Validate(payload, SettingsStore.ManagedKeys(), out _);
        if (values is null) return Refused;
        try
        {
            SettingsStore.SaveValues(values);
            return Applied;
        }
        catch
        {
            return WriteFailed;
        }
    }
}
