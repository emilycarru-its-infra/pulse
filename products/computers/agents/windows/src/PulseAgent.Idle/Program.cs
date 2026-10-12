using System.Diagnostics;
using System.Runtime.InteropServices;
using PulseAgent.Core;

// Reports keyboard and mouse idle time for the session it runs in. Windows does not let the
// agent, running as SYSTEM, read another session's input time for the console, so this helper
// runs in each signed-in session (a scheduled task at log on) and writes idle\<session>.json
// every five seconds for the agent to read. It sends nothing and holds no user data.

var session = (uint)Process.GetCurrentProcess().SessionId;
using var single = new Mutex(true, $@"Local\{Identity.ProductKey}.Idle", out var first);
if (!first) return 0;

var path = Path.Combine(Identity.IdleDirectory, $"{session}.json");
while (true)
{
    try
    {
        Directory.CreateDirectory(Identity.IdleDirectory);
        var temp = path + ".tmp";
        File.WriteAllText(temp, IdleReport.Write(session, IdleSeconds(), DateTimeOffset.UtcNow));
        File.Move(temp, path, overwrite: true);
    }
    catch
    {
        // The agent falls back to the session's own idle figure when this file goes stale.
    }
    Thread.Sleep(TimeSpan.FromSeconds(5));
}

static int IdleSeconds()
{
    var info = new LASTINPUTINFO { cbSize = (uint)Marshal.SizeOf<LASTINPUTINFO>() };
    if (!GetLastInputInfo(ref info)) return 0;
    // Both are 32-bit tick counts; unsigned subtraction survives the 49-day wrap.
    var idleMs = unchecked((uint)Environment.TickCount - info.dwTime);
    return (int)(idleMs / 1000);
}

[DllImport("user32.dll")]
static extern bool GetLastInputInfo(ref LASTINPUTINFO info);

[StructLayout(LayoutKind.Sequential)]
struct LASTINPUTINFO
{
    public uint cbSize;
    public uint dwTime;
}
