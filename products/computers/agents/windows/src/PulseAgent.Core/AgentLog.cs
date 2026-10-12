namespace PulseAgent.Core;

/// <summary>The agent's log: one file a day, logs\&lt;cli&gt;-YYYY-MM-DD.log, each line
/// "[yyyy-MM-dd HH:mm:ss] LEVEL message", kept for 14 days.</summary>
public static class AgentLog
{
    private static readonly object gate = new();
    public static bool Verbose { get; set; }
    public static bool Echo { get; set; }
    public const int KeepDays = 14;

    public static string PathFor(DateTime day) =>
        Path.Combine(Identity.LogDirectory, $"{Identity.CliName}-{day:yyyy-MM-dd}.log");

    public static void Info(string message) => Write("INFO", message);
    public static void Warn(string message) => Write("WARN", message);
    public static void Error(string message) => Write("ERROR", message);

    public static void Debug(string message)
    {
        if (Verbose) Write("DEBUG", message);
    }

    internal static string FormatLine(DateTime at, string level, string message) =>
        $"[{at:yyyy-MM-dd HH:mm:ss}] {level,-5} {message}";

    private static void Write(string level, string message)
    {
        var now = DateTime.Now;
        var line = FormatLine(now, level, message);
        if (Echo) Console.WriteLine(line);
        try
        {
            lock (gate)
            {
                Directory.CreateDirectory(Identity.LogDirectory);
                File.AppendAllText(PathFor(now), line + Environment.NewLine);
            }
        }
        catch
        {
            // A log that cannot be written must never stop the agent.
        }
    }

    /// <summary>Deletes log files older than <see cref="KeepDays"/>.</summary>
    public static void Prune()
    {
        try
        {
            foreach (var file in Directory.EnumerateFiles(Identity.LogDirectory, $"{Identity.CliName}-*.log"))
            {
                if (File.GetLastWriteTime(file) < DateTime.Now.AddDays(-KeepDays)) File.Delete(file);
            }
        }
        catch
        {
        }
    }
}
