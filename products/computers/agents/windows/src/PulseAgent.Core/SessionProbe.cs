using System.Runtime.InteropServices;
using System.Security.AccessControl;
using System.Security.Principal;
using System.Text.Json;

namespace PulseAgent.Core;

/// <summary>What the agent sees of the person at the computer. It never keeps a username: the
/// session's user name is read only to tell whether anyone is signed in.</summary>
/// <param name="Active">Someone is signed in, at the console or over a remote session.</param>
/// <param name="Locked">That session is locked.</param>
/// <param name="IdleSeconds">Seconds since the last keyboard or mouse input in that session.</param>
/// <param name="SessionId">The Windows session the reading comes from, or null when nobody is signed in.</param>
/// <param name="IdleSource">Where the idle time came from: helper, session or none.</param>
public sealed record SessionSnapshot(bool Active, bool Locked, int IdleSeconds, uint? SessionId, string IdleSource)
{
    public static readonly SessionSnapshot Nobody = new(false, false, 0, null, "none");
}

/// <summary>Reads the interactive session through the Windows Terminal Services API.</summary>
public static class SessionProbe
{
    /// <summary>Idle readings older than this are ignored and the session's own figure is used.</summary>
    public static readonly TimeSpan IdleFreshness = TimeSpan.FromSeconds(30);

    /// <summary>The signed-in session: the console's when someone is signed in there, otherwise
    /// the first active remote session with a user.</summary>
    public static SessionSnapshot Read()
    {
        var console = WTSGetActiveConsoleSessionId();
        var candidates = new List<uint>();
        if (console != 0xFFFFFFFF) candidates.Add(console);
        candidates.AddRange(ActiveSessions().Where(id => id != console));

        foreach (var id in candidates)
        {
            if (Query(id) is not { HasUser: true } info) continue;
            var (idle, source) = HelperIdle(id) is { } helper
                ? (helper, "helper")
                : info.IdleSeconds is { } own ? (own, "session") : (0, "none");
            return new SessionSnapshot(true, info.Locked, idle, id, source);
        }
        return SessionSnapshot.Nobody;
    }

    /// <summary>The idle seconds the per-user helper last wrote for a session, if fresh. Users write
    /// these files and the agent reads them as SYSTEM, so a report counts only when it is a plain
    /// small file owned by the user signed in to that session: nobody can speak for another session.</summary>
    internal static int? HelperIdle(uint sessionId, DateTimeOffset? now = null)
    {
        try
        {
            var file = new FileInfo(Path.Combine(Identity.IdleDirectory, $"{sessionId}.json"));
            if (!file.Exists || file.Attributes.HasFlag(FileAttributes.ReparsePoint) || file.Length > 4096) return null;
            var owner = file.GetAccessControl(AccessControlSections.Owner).GetOwner(typeof(SecurityIdentifier));
            if (owner is null || owner != SessionUser(sessionId)) return null;
            var path = file.FullName;
            return IdleReport.Parse(File.ReadAllText(path), now ?? DateTimeOffset.UtcNow, IdleFreshness);
        }
        catch
        {
            return null;
        }
    }

    /// <summary>The account signed in to a session. Only SYSTEM can ask; anyone else gets null.</summary>
    private static SecurityIdentifier? SessionUser(uint sessionId)
    {
        if (!WTSQueryUserToken(sessionId, out var token)) return null;
        try
        {
            using var identity = new WindowsIdentity(token);
            return identity.User;
        }
        finally
        {
            CloseHandle(token);
        }
    }

    private sealed record SessionInfo(bool HasUser, bool Locked, int? IdleSeconds);

    private static IEnumerable<uint> ActiveSessions()
    {
        if (!WTSEnumerateSessions(IntPtr.Zero, 0, 1, out var buffer, out var count)) yield break;
        try
        {
            var size = Marshal.SizeOf<WTS_SESSION_INFO>();
            var ids = new List<uint>();
            for (var i = 0; i < count; i++)
            {
                var info = Marshal.PtrToStructure<WTS_SESSION_INFO>(buffer + i * size);
                if (info.State == WTSActive) ids.Add(info.SessionId);
            }
            foreach (var id in ids) yield return id;
        }
        finally
        {
            WTSFreeMemory(buffer);
        }
    }

    private static SessionInfo? Query(uint sessionId)
    {
        if (!WTSQuerySessionInformation(IntPtr.Zero, sessionId, WTSSessionInfoEx, out var buffer, out _))
            return null;
        try
        {
            // WTSINFOEXW: a DWORD level, then the level-1 data 8-byte aligned.
            if (Marshal.ReadInt32(buffer) != 1) return null;
            var data = Marshal.PtrToStructure<WTSINFOEX_LEVEL1_W>(buffer + 8);
            var hasUser = !string.IsNullOrEmpty(data.UserName);
            // SessionFlags: 0 locked, 1 unlocked, -1 unknown.
            var locked = data.SessionFlags == WTS_SESSIONSTATE_LOCK;
            int? idle = data.LastInputTime > 0 && data.CurrentTime >= data.LastInputTime
                ? (int)Math.Min(int.MaxValue, (data.CurrentTime - data.LastInputTime) / TimeSpan.TicksPerSecond)
                : null;
            return new SessionInfo(hasUser, locked, idle);
        }
        finally
        {
            WTSFreeMemory(buffer);
        }
    }

    private const int WTSActive = 0;
    private const int WTSSessionInfoEx = 25;
    private const int WTS_SESSIONSTATE_LOCK = 0;

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct WTS_SESSION_INFO
    {
        public uint SessionId;
        public string WinStationName;
        public int State;
    }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct WTSINFOEX_LEVEL1_W
    {
        public uint SessionId;
        public int SessionState;
        public int SessionFlags;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 33)] public string WinStationName;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 21)] public string UserName;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 18)] public string DomainName;
        public long LogonTime;
        public long ConnectTime;
        public long DisconnectTime;
        public long LastInputTime;
        public long CurrentTime;
    }

    [DllImport("kernel32.dll")]
    private static extern uint WTSGetActiveConsoleSessionId();

    [DllImport("wtsapi32.dll", CharSet = CharSet.Unicode, SetLastError = true, EntryPoint = "WTSEnumerateSessionsW")]
    private static extern bool WTSEnumerateSessions(IntPtr server, int reserved, int version, out IntPtr buffer, out int count);

    [DllImport("wtsapi32.dll", CharSet = CharSet.Unicode, SetLastError = true, EntryPoint = "WTSQuerySessionInformationW")]
    private static extern bool WTSQuerySessionInformation(IntPtr server, uint sessionId, int infoClass, out IntPtr buffer, out int bytes);

    [DllImport("wtsapi32.dll")]
    private static extern void WTSFreeMemory(IntPtr memory);

    [DllImport("wtsapi32.dll", SetLastError = true)]
    private static extern bool WTSQueryUserToken(uint sessionId, out IntPtr token);

    [DllImport("kernel32.dll")]
    private static extern bool CloseHandle(IntPtr handle);
}

/// <summary>The file the per-user idle helper writes for its session:
/// {"sessionId": 3, "idleSeconds": 42, "at": "2027-01-04T17:05:00Z"}.</summary>
public static class IdleReport
{
    public static string Write(uint sessionId, int idleSeconds, DateTimeOffset at) =>
        JsonSerializer.Serialize(new { sessionId, idleSeconds, at = at.UtcDateTime.ToString("yyyy-MM-ddTHH:mm:ssZ") });

    /// <summary>The idle seconds in a report, or null when it is unreadable or older than
    /// <paramref name="freshness"/>. The time since the report is added, since input stayed idle.</summary>
    public static int? Parse(string json, DateTimeOffset now, TimeSpan freshness)
    {
        try
        {
            using var doc = JsonDocument.Parse(json);
            var idle = doc.RootElement.GetProperty("idleSeconds").GetInt32();
            var at = DateTimeOffset.Parse(doc.RootElement.GetProperty("at").GetString()!);
            var age = now - at;
            if (idle < 0 || age > freshness || age < -freshness) return null;
            return idle + (int)Math.Max(0, age.TotalSeconds);
        }
        catch
        {
            return null;
        }
    }
}
