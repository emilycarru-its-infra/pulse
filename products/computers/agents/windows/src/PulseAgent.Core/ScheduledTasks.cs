using System.Text.RegularExpressions;
using System.Xml.Linq;

namespace PulseAgent.Core;

/// <summary>One scheduled task the agent installs, as the Prefs tab's Services card shows it.</summary>
public sealed record ScheduledTaskStatus(string Name, string State, string LastRun = "", string Trigger = "", string Program = "", string Note = "")
{
    public bool HasDetails => Program.Length > 0;
    public bool HasNote => Note.Length > 0;
}

/// <summary>
/// Reads the agent's scheduled tasks through the Task Scheduler COM API, which any user may query
/// for these tasks: no elevation, and nothing here starts, stops or changes one.
/// </summary>
public static partial class ScheduledTasks
{
    private const int FileNotFound = unchecked((int)0x80070002);
    private const int PathNotFound = unchecked((int)0x80070003);

    // LastTaskResult codes that are Task Scheduler's own rather than the program's exit code.
    private const int HasNotRun = 0x41303;
    private static readonly Dictionary<int, string> SchedulerResults = new()
    {
        [0x41300] = "Ready to run",
        [0x41301] = "Still running",
        [0x41302] = "Disabled",
        [HasNotRun] = "Has not run yet",
        [0x41306] = "Ended by the user",
        [unchecked((int)0x8004131F)] = "An instance was already running",
        [unchecked((int)0x800710E0)] = "Refused by the operator",
        [unchecked((int)0xC000013A)] = "Ended when Windows shut down",
    };

    private static readonly XNamespace Ns = "http://schemas.microsoft.com/windows/2004/02/mit/task";

    /// <summary>The tasks install.ps1 registers, in the order the card lists them.</summary>
    public static IReadOnlyList<string> Names => [Identity.AgentTaskName, Identity.IdleTaskName, Identity.ShutdownTaskName];

    public static IReadOnlyList<ScheduledTaskStatus> Read()
    {
        object folder;
        try
        {
            var type = Type.GetTypeFromProgID("Schedule.Service")
                ?? throw new InvalidOperationException("Task Scheduler is not available.");
            dynamic service = Activator.CreateInstance(type)!;
            service.Connect();
            folder = service.GetFolder(@"\");
        }
        catch (Exception ex)
        {
            return Names.Select(n => new ScheduledTaskStatus(n, "Unknown", Note: ex.Message)).ToList();
        }
        return Names.Select(n => ReadOne(folder, n)).ToList();
    }

    private static ScheduledTaskStatus ReadOne(object folder, string name)
    {
        try
        {
            var task = ((dynamic)folder).GetTask(name);
            var (trigger, program) = DescribeDefinition((string)task.Xml);
            return new ScheduledTaskStatus(name, DescribeState((int)task.State, (bool)task.Enabled),
                DescribeLastRun((DateTime)task.LastRunTime, (int)task.LastTaskResult), trigger, program);
        }
        // The COM call surfaces a missing task as FileNotFoundException, not COMException.
        catch (Exception ex) when (ex.HResult is FileNotFound or PathNotFound)
        {
            return new ScheduledTaskStatus(name, "Not installed");
        }
        catch (UnauthorizedAccessException)
        {
            return new ScheduledTaskStatus(name, "Unknown", Note: "This account may not read the task.");
        }
        catch (Exception ex)
        {
            return new ScheduledTaskStatus(name, "Unknown", Note: ex.Message);
        }
    }

    /// <summary>The TASK_STATE value as a word; a disabled task reads Disabled whatever its state.</summary>
    internal static string DescribeState(int state, bool enabled) => !enabled ? "Disabled" : state switch
    {
        1 => "Disabled",
        2 => "Queued",
        3 => "Ready",
        4 => "Running",
        _ => "Unknown",
    };

    /// <summary>When the task last ran and how it ended: the program's exit code, or Task
    /// Scheduler's own word for the result.</summary>
    internal static string DescribeLastRun(DateTime lastRun, int result)
    {
        // A task that has never run reports 1899-12-30 or 1999-11-30 rather than no date.
        if (result == HasNotRun || lastRun.Year < 2000) return "Has not run yet";
        var outcome = SchedulerResults.TryGetValue(result, out var known) ? known
            : result == 0 ? "Exit code 0"
            : result is > 0 and < 0x10000 ? $"Exit code {result}"
            : $"Result 0x{result:X8}";
        return $"{lastRun:yyyy-MM-dd HH:mm}, {outcome}";
    }

    /// <summary>The triggers and the program from a task's XML definition.</summary>
    internal static (string Trigger, string Program) DescribeDefinition(string xml)
    {
        var root = XDocument.Parse(xml).Root!;
        var triggers = root.Element(Ns + "Triggers")?.Elements()
            .Where(t => (string?)t.Element(Ns + "Enabled") != "false")
            .Select(DescribeTrigger).ToList() ?? [];
        var programs = root.Element(Ns + "Actions")?.Elements(Ns + "Exec").Select(e =>
        {
            var command = ((string?)e.Element(Ns + "Command") ?? "").Trim().Trim('"');
            var arguments = ((string?)e.Element(Ns + "Arguments") ?? "").Trim();
            return arguments.Length > 0 ? $"{command} {arguments}" : command;
        }).ToList() ?? [];
        return (triggers.Count > 0 ? string.Join("; ", triggers) : "No trigger", string.Join("; ", programs));
    }

    private static string DescribeTrigger(XElement trigger)
    {
        switch (trigger.Name.LocalName)
        {
            case "BootTrigger":
                return "At startup";
            case "LogonTrigger":
                return trigger.Element(Ns + "UserId") is null ? "At log on of any user" : "At log on";
            case "EventTrigger":
                var subscription = (string?)trigger.Element(Ns + "Subscription") ?? "";
                var id = EventIdPattern().Match(subscription);
                var log = LogPattern().Match(subscription);
                return id.Success
                    ? $"On event {id.Groups[1].Value}{(log.Success ? $" in the {log.Groups[1].Value} log" : "")}"
                    : "On an event";
            case "TimeTrigger":
            case "CalendarTrigger":
                var repeat = (string?)trigger.Element(Ns + "Repetition")?.Element(Ns + "Interval");
                return repeat is null ? "On a schedule" : $"Every {DescribeInterval(System.Xml.XmlConvert.ToTimeSpan(repeat))}";
            case "IdleTrigger":
                return "When the computer is idle";
            case "SessionStateChangeTrigger":
                return "On a session change";
            default:
                return trigger.Name.LocalName;
        }
    }

    internal static string DescribeInterval(TimeSpan interval) =>
        interval.TotalDays >= 1 && interval.TotalDays % 1 == 0 ? Plural((int)interval.TotalDays, "day")
        : interval.TotalHours >= 1 && interval.TotalHours % 1 == 0 ? Plural((int)interval.TotalHours, "hour")
        : interval.TotalMinutes >= 1 && interval.TotalMinutes % 1 == 0 ? Plural((int)interval.TotalMinutes, "minute")
        : Plural((int)interval.TotalSeconds, "second");

    private static string Plural(int n, string unit) => n == 1 ? unit : $"{n} {unit}s";

    [GeneratedRegex(@"EventID\s*=\s*(\d+)")]
    private static partial Regex EventIdPattern();

    [GeneratedRegex(@"<Select\s+Path=""([^""]+)""")]
    private static partial Regex LogPattern();
}
