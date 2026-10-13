using System.ComponentModel;
using System.Text.RegularExpressions;
using System.Xml.Linq;

namespace PulseAgent.Core;

/// <summary>How a task's state dot reads: green when it is ready or running and its last run
/// ended well, gray when it is disabled, not installed or cannot be read, red only when its last
/// run failed.</summary>
public enum StatusTone { Healthy, Inactive, Failed }

/// <summary>One labelled line in a task's expanded detail. Paths and command lines are monospace.</summary>
public sealed record StatusDetail(string Label, string Value, bool Monospace = false);

/// <summary>One scheduled task the agent installs, as the Prefs tab's Services card shows it: a
/// collapsed row of name, one summary line and state, and the detail that expands under it.</summary>
public sealed record ScheduledTaskStatus(string Name, string State, StatusTone Tone = StatusTone.Inactive,
    IReadOnlyList<StatusDetail>? Details = null, string Note = "", string Summary = ScheduledTasks.Kind)
{
    public IReadOnlyList<StatusDetail> Details { get; init; } = Details ?? [];
    public bool HasNote => Note.Length > 0;
    /// <summary>The row as a screen reader says it, since the dot carries the state by colour alone.</summary>
    public string AccessibleName => $"{Name}, {State}";
}

/// <summary>A task's definition as its XML holds it: who wrote it, when it runs, what it runs
/// and as whom.</summary>
public sealed record TaskDefinition(string Author, string Description, bool Hidden, string Trigger,
    IReadOnlyList<TaskAction> Actions, string RunAs, string RunLevel);

/// <summary>One Exec action: the program, its arguments and the folder it starts in.</summary>
public sealed record TaskAction(string Program, string Arguments, string WorkingDirectory);

/// <summary>What Task Scheduler reports about a registered task, before any of it is put into words.</summary>
public sealed record TaskSnapshot(string Name, string Path, bool Enabled, int State, DateTime LastRun, int LastResult,
    DateTime NextRun, TaskDefinition Definition);

/// <summary>
/// Reads the agent's scheduled tasks through the Task Scheduler COM API, which any user may query
/// for these tasks: no elevation, and nothing here starts, stops or changes one. The detail follows
/// the fields ReportMate's System module collects for a scheduled task.
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
        [0x40010004] = "Ended by Windows, as at sign-out",
    };

    // Results that say how a run ended without saying it failed: a long-running task stopped by an
    // install, a sign-out or a shutdown is not a fault.
    private static readonly HashSet<int> Benign =
        [0, 0x41300, 0x41301, HasNotRun, 0x41306, unchecked((int)0x8004131F), unchecked((int)0xC000013A), 0x40010004];

    private static readonly XNamespace Ns = "http://schemas.microsoft.com/windows/2004/02/mit/task";

    /// <summary>The tasks install.ps1 registers, in the order the card lists them.</summary>
    /// <summary>What the collapsed row's summary line opens with.</summary>
    public const string Kind = "Scheduled task";

    public static IReadOnlyList<string> Names => [Identity.AgentTaskName, Identity.IdleTaskName, Identity.ShutdownTaskName];

    /// <summary>Whether the agent ships any task at all; the Services card is hidden when not.</summary>
    public static bool AnyDefined => Names.Count > 0;

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
            return Describe(new TaskSnapshot(name, (string)task.Path, (bool)task.Enabled, (int)task.State,
                (DateTime)task.LastRunTime, (int)task.LastTaskResult, (DateTime)task.NextRunTime,
                ParseDefinition((string)task.Xml)));
        }
        // The COM call surfaces a missing task as FileNotFoundException, not COMException.
        catch (Exception ex) when (ex.HResult is FileNotFound or PathNotFound)
        {
            return new ScheduledTaskStatus(name, "Not installed",
                Note: "Task Scheduler has no task by this name. Installing the agent registers it.");
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

    /// <summary>A registered task as the card shows it: its state, dot and every detail line.</summary>
    public static ScheduledTaskStatus Describe(TaskSnapshot task)
    {
        var state = DescribeState(task.State, task.Enabled);
        var definition = task.Definition;
        var ran = !NeverRan(task.LastRun, task.LastResult);
        var details = new List<StatusDetail>
        {
            new("Path", task.Path, Monospace: true),
            new("Folder", FolderOf(task.Path), Monospace: true),
            new("State", state),
            new("Enabled", task.Enabled ? "Yes" : "No"),
            new("Hidden", definition.Hidden ? "Yes" : "No"),
            new("Last run", ran ? FormatTime(task.LastRun) : "Has not run yet"),
        };
        if (ran) details.Add(new("Last result", DescribeResult(task.LastResult)));
        details.Add(new("Next run", task.NextRun.Year < 2000 ? "None scheduled; it runs on its trigger" : FormatTime(task.NextRun)));
        details.Add(new("Triggers", definition.Trigger));
        var numbered = definition.Actions.Count > 1;
        for (var i = 0; i < definition.Actions.Count; i++)
        {
            var action = definition.Actions[i];
            var suffix = numbered ? $" {i + 1}" : "";
            details.Add(new($"Program{suffix}", action.Program, Monospace: true));
            if (action.Arguments.Length > 0) details.Add(new($"Arguments{suffix}", action.Arguments, Monospace: true));
            if (action.WorkingDirectory.Length > 0) details.Add(new($"Starts in{suffix}", action.WorkingDirectory, Monospace: true));
        }
        details.Add(new("Run as", definition.RunAs));
        details.Add(new("Run level", definition.RunLevel));
        if (definition.Author.Length > 0) details.Add(new("Author", definition.Author));
        if (definition.Description.Length > 0) details.Add(new("Description", definition.Description));
        return new ScheduledTaskStatus(task.Name, state, ToneOf(task.Enabled, task.State, ran ? task.LastResult : HasNotRun), details,
            Summary: SummaryLine(definition.Trigger, ran, task.LastResult));
    }

    /// <summary>The collapsed row's second line: what it is, when it runs and how it last ended,
    /// as in "Scheduled task · At startup · Last result 0x0".</summary>
    internal static string SummaryLine(string trigger, bool ran, int lastResult)
    {
        var last = ran ? $"Last result 0x{lastResult:X}" : "Has not run yet";
        return string.Join(" · ", new[] { Kind, trigger, last }.Where(p => p.Length > 0));
    }

    /// <summary>Gray when disabled, red when the last run failed, green otherwise.</summary>
    internal static StatusTone ToneOf(bool enabled, int state, int lastResult) =>
        !enabled || state == 1 ? StatusTone.Inactive
        : state is not (2 or 3 or 4) ? StatusTone.Inactive
        : Benign.Contains(lastResult) ? StatusTone.Healthy
        : StatusTone.Failed;

    /// <summary>The TASK_STATE value as a word; a disabled task reads Disabled whatever its state.</summary>
    internal static string DescribeState(int state, bool enabled) => !enabled ? "Disabled" : state switch
    {
        1 => "Disabled",
        2 => "Queued",
        3 => "Ready, not running",
        4 => "Running",
        _ => "Unknown",
    };

    // A task that has never run reports 1899-12-30 or 1999-11-30 rather than no date.
    private static bool NeverRan(DateTime lastRun, int result) => result == HasNotRun || lastRun.Year < 2000;

    private static string FormatTime(DateTime when) => $"{when:yyyy-MM-dd HH:mm}";

    /// <summary>The folder part of a task path: \ for a task at the root.</summary>
    internal static string FolderOf(string path)
    {
        var slash = path.LastIndexOf('\\');
        return slash <= 0 ? @"\" : path[..slash];
    }

    /// <summary>A LastTaskResult as hex and what it means: 0x00000002 (Exit code 2).</summary>
    internal static string DescribeResult(int result) => $"0x{result:X8} ({Outcome(result)})";

    private static string Outcome(int result)
    {
        if (SchedulerResults.TryGetValue(result, out var known)) return known;
        if (result == 0) return "Exit code 0, success";
        if (result is > 0 and < 0x10000) return $"Exit code {result}";
        // A Win32 error wrapped as an HRESULT (0x8007xxxx) has a system message; anything else is
        // reported by its number alone.
        if ((uint)result >> 16 == 0x8007)
        {
            var message = new Win32Exception(result & 0xFFFF).Message;
            if (!message.StartsWith("Unknown error", StringComparison.OrdinalIgnoreCase)) return message.TrimEnd('.');
        }
        return "Unrecognized result";
    }

    /// <summary>A task's definition from its XML: triggers in plain words, its Exec actions, the
    /// account it runs as and at what level, and its author.</summary>
    public static TaskDefinition ParseDefinition(string xml)
    {
        var root = XDocument.Parse(xml).Root!;
        var triggers = root.Element(Ns + "Triggers")?.Elements()
            .Where(t => (string?)t.Element(Ns + "Enabled") != "false")
            .Select(DescribeTrigger).ToList() ?? [];
        var actions = root.Element(Ns + "Actions")?.Elements(Ns + "Exec").Select(e => new TaskAction(
            ((string?)e.Element(Ns + "Command") ?? "").Trim().Trim('"'),
            ((string?)e.Element(Ns + "Arguments") ?? "").Trim(),
            ((string?)e.Element(Ns + "WorkingDirectory") ?? "").Trim().Trim('"'))).ToList() ?? [];
        var info = root.Element(Ns + "RegistrationInfo");
        var principal = root.Element(Ns + "Principals")?.Element(Ns + "Principal");
        return new TaskDefinition(
            ((string?)info?.Element(Ns + "Author") ?? "").Trim(),
            ((string?)info?.Element(Ns + "Description") ?? "").Trim(),
            (string?)root.Element(Ns + "Settings")?.Element(Ns + "Hidden") == "true",
            triggers.Count > 0 ? string.Join("; ", triggers) : "No trigger",
            actions,
            DescribePrincipal(principal),
            (string?)principal?.Element(Ns + "RunLevel") == "HighestAvailable" ? "Highest privileges" : "Standard privileges");
    }

    // The well-known accounts install.ps1 and Windows use, by SID, so the card names them
    // without a directory lookup.
    private static readonly Dictionary<string, string> KnownAccounts = new(StringComparer.OrdinalIgnoreCase)
    {
        ["S-1-5-18"] = "SYSTEM",
        ["S-1-5-19"] = "LOCAL SERVICE",
        ["S-1-5-20"] = "NETWORK SERVICE",
        ["S-1-5-4"] = "INTERACTIVE",
        ["S-1-5-32-544"] = "Administrators",
        ["S-1-5-32-545"] = "Users",
    };

    /// <summary>The account or group a task runs as: SYSTEM, or "Any member of Users".</summary>
    internal static string DescribePrincipal(XElement? principal)
    {
        if (principal is null) return "The account that registered it";
        var user = ((string?)principal.Element(Ns + "UserId") ?? "").Trim();
        var group = ((string?)principal.Element(Ns + "GroupId") ?? "").Trim();
        if (user.Length > 0) return KnownAccounts.GetValueOrDefault(user, user);
        if (group.Length > 0) return $"Any member of {KnownAccounts.GetValueOrDefault(group, group)}";
        return "The account that registered it";
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
