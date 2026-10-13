using System.ComponentModel;
using System.Diagnostics;
using System.IO.Pipes;
using System.Runtime.InteropServices;
using System.Security.AccessControl;
using System.Security.Principal;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace PulseAgent.Core;

/// <summary>
/// How the GUI saves settings without running elevated. Settings live in HKLM, so a change made
/// in an unelevated GUI is handed to a copy of the app started through UAC in a hidden apply mode.
/// Only a random pipe name goes on that copy's command line: the GUI writes the changed keys to
/// the pipe once, and the copy reads them only after checking that the process serving the pipe is
/// this same app, installed under Program Files. So nothing secret is on a command line, and a
/// process that starts the apply mode itself cannot choose the values the UAC prompt approves.
/// The copy checks every key itself, writes HKLM and exits; it never shows a window. No service
/// and no file sits between them.
/// </summary>
public static partial class PrefsElevation
{
    /// <summary>Command-line switch for the hidden apply mode; the pipe name follows it.</summary>
    public const string ApplyArgument = "--apply-settings";

    /// <summary>Win32 ERROR_CANCELLED: the user dismissed the UAC prompt.</summary>
    public const int ErrorCancelled = 1223;

    /// <summary>Exit codes of the apply mode.</summary>
    public const int Applied = 0;
    public const int WriteFailed = 1;
    public const int Refused = 2;

    /// <summary>The largest payload either side accepts; the settings are a few hundred bytes.</summary>
    public const int MaxPayloadBytes = 64 * 1024;

    /// <summary>How long the apply mode waits for the pipe and its payload before giving up.</summary>
    public static readonly TimeSpan PipeTimeout = TimeSpan.FromSeconds(15);

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

    // ---- The GUI's side ----

    /// <summary>
    /// Runs <paramref name="exePath"/> elevated in the apply mode, hands it the changed keys over a
    /// fresh pipe and returns its exit code. Throws the Win32Exception for a cancelled UAC prompt.
    /// </summary>
    public static async Task<int> RunElevatedApplyAsync(string exePath, IReadOnlyDictionary<string, object> changes)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(exePath);
        var pipeName = NewPipeName();
        using var server = CreatePipe(pipeName);
        // ShellExecute waits on the UAC prompt, so it runs off the caller's thread.
        using var process = await Task.Run(() => Process.Start(BuildElevatedApply(exePath, pipeName)))
            ?? throw new InvalidOperationException("The administrator copy of the app did not start.");

        // The copy may exit without connecting, having refused; then stop waiting for it.
        using var stop = new CancellationTokenSource();
        var exited = process.WaitForExitAsync();
        var connected = server.WaitForConnectionAsync(stop.Token);
        if (await Task.WhenAny(connected, exited) == connected && connected.IsCompletedSuccessfully)
        {
            // The pipe has no buffer, so the write finishes as the copy reads it. A copy that
            // refuses closes the pipe first; its exit code then says so.
            try
            {
                await WriteFrameAsync(server, JsonSerializer.Serialize(changes));
                await server.FlushAsync();
                server.WaitForPipeDrain();
            }
            catch (IOException)
            {
            }
        }
        else
        {
            stop.Cancel();
        }
        await exited;
        return process.ExitCode;
    }

    /// <summary>A pipe name nobody can guess: the product, then 128 random bits.</summary>
    public static string NewPipeName() => $"{Identity.ProductKey}.Apply.{Guid.NewGuid():N}";

    public static bool IsPipeName(string? name)
        => name is not null && name.StartsWith($"{Identity.ProductKey}.Apply.", StringComparison.Ordinal)
           && PipeSuffix().IsMatch(name[(Identity.ProductKey.Length + 7)..]);

    /// <summary>One instance, outbound only, which only this user and Administrators may open:
    /// the elevated copy runs as this user, or as the administrator who approved the prompt.</summary>
    private static NamedPipeServerStream CreatePipe(string name)
    {
        var security = new PipeSecurity();
        using (var me = WindowsIdentity.GetCurrent())
            security.AddAccessRule(new PipeAccessRule(me.User!, PipeAccessRights.FullControl, AccessControlType.Allow));
        security.AddAccessRule(new PipeAccessRule(new SecurityIdentifier(WellKnownSidType.BuiltinAdministratorsSid, null),
            PipeAccessRights.ReadWrite, AccessControlType.Allow));
        return NamedPipeServerStreamAcl.Create(name, PipeDirection.Out, 1, PipeTransmissionMode.Byte,
            PipeOptions.Asynchronous, 0, 0, security);
    }

    /// <summary>Start info that runs <paramref name="exePath"/> elevated in the apply mode.</summary>
    public static ProcessStartInfo BuildElevatedApply(string exePath, string pipeName)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(exePath);
        return new ProcessStartInfo
        {
            FileName = exePath,
            Arguments = $"{ApplyArgument} {pipeName}",
            UseShellExecute = true,
            Verb = "runas",
            WindowStyle = ProcessWindowStyle.Hidden,
            WorkingDirectory = Path.GetDirectoryName(exePath) ?? string.Empty,
        };
    }

    // ---- The payload on the pipe: a 4-byte little-endian length, then that much UTF-8 JSON ----

    public static async Task WriteFrameAsync(Stream stream, string json, CancellationToken cancel = default)
    {
        var body = Encoding.UTF8.GetBytes(json);
        if (body.Length > MaxPayloadBytes) throw new InvalidDataException("The settings are too large to send.");
        var frame = new byte[4 + body.Length];
        BitConverter.TryWriteBytes(frame.AsSpan(0, 4), body.Length);
        if (!BitConverter.IsLittleEndian) frame.AsSpan(0, 4).Reverse();
        body.CopyTo(frame, 4);
        await stream.WriteAsync(frame, cancel);
    }

    /// <summary>The JSON in one frame, or null when the stream ends early or claims a length
    /// outside 1 to MaxPayloadBytes.</summary>
    public static async Task<string?> ReadFrameAsync(Stream stream, CancellationToken cancel = default)
    {
        var header = new byte[4];
        if (!await ReadExactlyAsync(stream, header, cancel)) return null;
        var length = header[0] | header[1] << 8 | header[2] << 16 | header[3] << 24;
        if (length is <= 0 or > MaxPayloadBytes) return null;
        var body = new byte[length];
        return await ReadExactlyAsync(stream, body, cancel) ? Encoding.UTF8.GetString(body) : null;
    }

    private static async Task<bool> ReadExactlyAsync(Stream stream, byte[] buffer, CancellationToken cancel)
    {
        try
        {
            await stream.ReadExactlyAsync(buffer, cancel);
            return true;
        }
        catch (EndOfStreamException)
        {
            return false;
        }
    }

    // ---- The apply mode's side ----

    /// <summary>The pipe name when <paramref name="args"/> asks for the apply mode, else null.
    /// An apply switch with nothing after it gives an empty name, which Apply refuses.</summary>
    public static string? ApplyPipeName(IReadOnlyList<string> args)
    {
        for (var i = 0; i < args.Count; i++)
        {
            if (string.Equals(args[i]?.Trim(), ApplyArgument, StringComparison.OrdinalIgnoreCase))
                return i + 1 < args.Count ? args[i + 1] : "";
        }
        return null;
    }

    /// <summary>
    /// Whether the process serving the pipe may hand this one settings: its image must be this very
    /// executable, and that executable must sit under one of <paramref name="trustedRoots"/>, folders
    /// a user cannot write to. Paths are compared as Windows reports them, ignoring case; a path
    /// with . or .. segments, or a root that is only a name prefix, never matches.
    /// </summary>
    public static bool IsTrustedServer(string? serverImage, string? ownImage, IEnumerable<string> trustedRoots)
    {
        static string? Clean(string? path)
        {
            if (string.IsNullOrWhiteSpace(path)) return null;
            var p = path.Trim().Replace('/', '\\');
            if (p.StartsWith(@"\\", StringComparison.Ordinal)) return null;
            if (p.Split('\\').Any(part => part is "." or "..")) return null;
            return p;
        }
        var server = Clean(serverImage);
        var own = Clean(ownImage);
        if (server is null || own is null || !string.Equals(server, own, StringComparison.OrdinalIgnoreCase)) return false;
        return trustedRoots.Select(Clean).OfType<string>()
            .Any(root => own.StartsWith(root.TrimEnd('\\') + '\\', StringComparison.OrdinalIgnoreCase));
    }

    /// <summary>Program Files, both views: the folders the installer uses and users cannot write.</summary>
    public static IEnumerable<string> TrustedRoots() =>
        new[] { Environment.SpecialFolder.ProgramFiles, Environment.SpecialFolder.ProgramFilesX86 }
            .Select(Environment.GetFolderPath).Where(p => p.Length > 0);

    /// <summary>
    /// Checks the JSON payload as the save code would: only known keys, never one policy
    /// manages, each of the right type, intervals clamped to their ranges. Returns the values to
    /// write, or null with the reason.
    /// </summary>
    public static Dictionary<string, object>? Validate(string json, IReadOnlySet<string> managed, out string error)
    {
        error = "";
        Dictionary<string, JsonElement>? raw;
        try
        {
            raw = JsonSerializer.Deserialize<Dictionary<string, JsonElement>>(json);
        }
        catch (JsonException)
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

    /// <summary>The apply mode itself: opens the GUI's pipe, makes sure this app is serving it,
    /// reads the changed keys, checks them against the policy on this device, writes HKLM and
    /// returns the exit code. Anything unexpected is Refused, with nothing written.</summary>
    public static int Apply(string pipeName)
    {
        if (!IsPipeName(pipeName)) return Refused;
        string? json;
        try
        {
            using var client = new NamedPipeClientStream(".", pipeName, PipeDirection.In, PipeOptions.Asynchronous);
            client.Connect(PipeTimeout);
            if (!IsTrustedServer(PipeServerImage(client), Environment.ProcessPath, TrustedRoots())) return Refused;
            using var timeout = new CancellationTokenSource(PipeTimeout);
            json = ReadFrameAsync(client, timeout.Token).GetAwaiter().GetResult();
        }
        catch
        {
            return Refused;
        }
        if (json is null) return Refused;

        var values = Validate(json, SettingsStore.ManagedKeys(), out _);
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

    /// <summary>The full image path of the process serving the pipe, or null.</summary>
    private static string? PipeServerImage(NamedPipeClientStream client)
    {
        if (!GetNamedPipeServerProcessId(client.SafePipeHandle, out var pid)) return null;
        var process = OpenProcess(ProcessQueryLimitedInformation, false, pid);
        if (process == IntPtr.Zero) return null;
        try
        {
            var buffer = new StringBuilder(32768);
            var size = buffer.Capacity;
            return QueryFullProcessImageName(process, 0, buffer, ref size) ? buffer.ToString(0, size) : null;
        }
        finally
        {
            CloseHandle(process);
        }
    }

    private const uint ProcessQueryLimitedInformation = 0x1000;

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool GetNamedPipeServerProcessId(Microsoft.Win32.SafeHandles.SafePipeHandle pipe, out uint processId);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern IntPtr OpenProcess(uint access, bool inherit, uint processId);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true, EntryPoint = "QueryFullProcessImageNameW")]
    private static extern bool QueryFullProcessImageName(IntPtr process, uint flags, StringBuilder name, ref int size);

    [DllImport("kernel32.dll")]
    private static extern bool CloseHandle(IntPtr handle);

    [GeneratedRegex("^[0-9a-f]{32}$")]
    private static partial Regex PipeSuffix();
}
