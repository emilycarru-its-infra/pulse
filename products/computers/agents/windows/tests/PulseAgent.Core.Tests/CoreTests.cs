using System.Text.Json;
using PulseAgent.Core;
using Xunit;

namespace PulseAgent.Core.Tests;

public class EventTests
{
    private static readonly SessionSnapshot InUse = new(true, false, 42, 3, "helper");

    [Fact]
    public void EventMatchesTheContract()
    {
        var json = PulseEvent.Create("heartbeat", InUse, "LAB-PC-01", "EXAMPLE-SERIAL",
            new DateTimeOffset(2027, 1, 4, 17, 5, 0, TimeSpan.Zero), "2027.01.04.1705").ToJson();
        using var doc = JsonDocument.Parse(json);
        using var schema = JsonDocument.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "event.schema.json")));
        AssertShape(doc.RootElement, schema.RootElement);
        Assert.Equal("2027-01-04T17:05:00Z", doc.RootElement.GetProperty("ts").GetString());
        Assert.Equal("windows", doc.RootElement.GetProperty("agent").GetProperty("platform").GetString());
        Assert.Equal(42, doc.RootElement.GetProperty("session").GetProperty("idleSeconds").GetInt32());
    }

    // Every property the schema requires is present and nothing it does not allow is, all the way down.
    private static void AssertShape(JsonElement value, JsonElement schema)
    {
        if (!schema.TryGetProperty("properties", out var props)) return;
        var allowed = props.EnumerateObject().Select(p => p.Name).ToHashSet();
        var present = value.EnumerateObject().Select(p => p.Name).ToHashSet();
        Assert.Subset(allowed, present);
        foreach (var required in schema.GetProperty("required").EnumerateArray())
            Assert.Contains(required.GetString()!, present);
        foreach (var p in value.EnumerateObject())
            AssertShape(p.Value, props.GetProperty(p.Name));
    }

    [Fact]
    public void NobodySignedInIsNeverLocked()
    {
        var pulse = PulseEvent.Create("heartbeat", new SessionSnapshot(false, true, 5, null, "none"), "H", "S", DateTimeOffset.UtcNow, "v");
        Assert.False(pulse.Session.Locked);
    }

    [Fact]
    public void UnknownTypeIsRefused() =>
        Assert.Throws<ArgumentException>(() => PulseEvent.Create("nap", InUse, "H", "S", DateTimeOffset.UtcNow, "v"));
}

public class TransitionTests
{
    private static SessionSnapshot S(bool active, bool locked = false, uint? id = 1) => new(active, locked, 0, active ? id : null, "none");

    [Theory]
    [InlineData(false, false, true, false, "login")]
    [InlineData(false, false, true, true, "login,lock")]
    [InlineData(true, false, false, false, "logout")]
    [InlineData(true, false, true, true, "lock")]
    [InlineData(true, true, true, false, "unlock")]
    [InlineData(true, false, true, false, "")]
    public void EventsFollowTheSession(bool a1, bool l1, bool a2, bool l2, string expected) =>
        Assert.Equal(expected, string.Join(",", Transitions.Between(S(a1, l1), S(a2, l2))));

    [Fact]
    public void ANewSessionIsALogoutThenALogin() =>
        Assert.Equal(["logout", "login"], Transitions.Between(S(true, id: 1), S(true, id: 2)));

    [Fact]
    public void SeatStateMirrorsTheServer()
    {
        Assert.Equal("available", Transitions.SeatState(S(false)));
        Assert.Equal("in_use", Transitions.SeatState(new SessionSnapshot(true, false, 899, 1, "helper")));
        Assert.Equal("possibly_free", Transitions.SeatState(new SessionSnapshot(true, false, 900, 1, "helper")));
        Assert.Equal("possibly_free", Transitions.SeatState(S(true, locked: true)));
    }
}

public class SettingsTests
{
    [Fact]
    public void PolicyWinsOverMachineWhichWinsOverDefaults()
    {
        var policy = new Dictionary<string, object> { ["IngestUrl"] = "https://policy.example/api/ingest" };
        var machine = new Dictionary<string, object> { ["IngestUrl"] = "https://machine.example", ["CheckIntervalSeconds"] = 20, ["VerboseLogging"] = 1 };
        var s = SettingsStore.Resolve(k => policy.GetValueOrDefault(k), k => machine.GetValueOrDefault(k));
        Assert.Equal("https://policy.example/api/ingest", s.IngestUrl);
        Assert.Equal(20, s.CheckIntervalSeconds);
        Assert.Equal(60, s.HeartbeatIntervalSeconds);
        Assert.True(s.VerboseLogging);
        Assert.True(s.UseDeviceCertificate);
    }

    [Fact]
    public void IntervalsAreClampedAndHeartbeatIsNeverShorterThanTheCheck()
    {
        var machine = new Dictionary<string, object> { ["CheckIntervalSeconds"] = "1", ["HeartbeatIntervalSeconds"] = 3 };
        var s = SettingsStore.Resolve(_ => null, k => machine.GetValueOrDefault(k));
        Assert.Equal(5, s.CheckIntervalSeconds);
        Assert.Equal(15, s.HeartbeatIntervalSeconds);
    }

    [Fact]
    public void TheSharedKeyComesOnlyFromTheSecretsKey()
    {
        var readable = new Dictionary<string, object> { ["IngestKey"] = "leaked" };
        Assert.Null(SettingsStore.Resolve(k => readable.GetValueOrDefault(k), k => readable.GetValueOrDefault(k)).IngestKey);
        Assert.Equal("s3cret", SettingsStore.Resolve(_ => null, _ => null, k => k == "IngestKey" ? "s3cret" : null).IngestKey);
        Assert.DoesNotContain("IngestKey", SettingsStore.Keys);
    }

    [Fact]
    public void BlankStringsAreUnset() => Assert.Null(SettingsStore.AsString("  "));
}

public class IdleReportTests
{
    private static readonly DateTimeOffset Now = new(2027, 1, 4, 17, 5, 0, TimeSpan.Zero);

    [Fact]
    public void AFreshReportCountsTheSecondsSinceItWasWritten() =>
        Assert.Equal(52, IdleReport.Parse(IdleReport.Write(3, 42, Now.AddSeconds(-10)), Now, TimeSpan.FromSeconds(30)));

    [Fact]
    public void AStaleOrBrokenReportIsIgnored()
    {
        Assert.Null(IdleReport.Parse(IdleReport.Write(3, 42, Now.AddMinutes(-2)), Now, TimeSpan.FromSeconds(30)));
        Assert.Null(IdleReport.Parse("{", Now, TimeSpan.FromSeconds(30)));
    }
}

public class IdentityTests
{
    [Fact]
    public void VersionReadsAsDateAndTime() => Assert.Equal("v2026.10.05 (1342)", Identity.FormatVersion("2026.10.05.1342"));

    [Fact]
    public void LogLinesCarryAPaddedLevel() =>
        Assert.Equal("[2027-01-04 17:05:00] WARN  late", AgentLog.FormatLine(new DateTime(2027, 1, 4, 17, 5, 0), "WARN", "late"));
}

public class ScheduledTaskTests
{
    private const string AgentXml = """
        <?xml version="1.0" encoding="UTF-16"?>
        <Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
          <Triggers><BootTrigger><Enabled>true</Enabled></BootTrigger></Triggers>
          <Actions Context="Author">
            <Exec>
              <Command>"C:\Program Files\Example\agent.exe"</Command>
              <Arguments>run</Arguments>
            </Exec>
          </Actions>
        </Task>
        """;

    private const string ShutdownXml = """
        <Task xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
          <Triggers>
            <EventTrigger>
              <Enabled>true</Enabled>
              <Subscription>&lt;QueryList&gt;&lt;Query Id="0" Path="System"&gt;&lt;Select Path="System"&gt;*[System[Provider[@Name='User32'] and EventID=1074]]&lt;/Select&gt;&lt;/Query&gt;&lt;/QueryList&gt;</Subscription>
            </EventTrigger>
            <LogonTrigger><Enabled>false</Enabled></LogonTrigger>
          </Triggers>
          <Actions><Exec><Command>C:\agent.exe</Command></Exec></Actions>
        </Task>
        """;

    [Fact]
    public void BootTaskReadsItsTriggerAndProgram()
    {
        var (trigger, program) = ScheduledTasks.DescribeDefinition(AgentXml.Trim());
        Assert.Equal("At startup", trigger);
        Assert.Equal(@"C:\Program Files\Example\agent.exe run", program);
    }

    [Fact]
    public void EventTaskNamesTheEventAndSkipsADisabledTrigger()
    {
        var (trigger, program) = ScheduledTasks.DescribeDefinition(ShutdownXml);
        Assert.Equal("On event 1074 in the System log", trigger);
        Assert.Equal(@"C:\agent.exe", program);
    }

    [Theory]
    [InlineData("PT6H", "6 hours")]
    [InlineData("PT1H", "hour")]
    [InlineData("PT90M", "90 minutes")]
    [InlineData("P1D", "day")]
    public void IntervalsReadAsWords(string xml, string expected) =>
        Assert.Equal(expected, ScheduledTasks.DescribeInterval(System.Xml.XmlConvert.ToTimeSpan(xml)));

    [Theory]
    [InlineData(3, true, "Ready")]
    [InlineData(4, true, "Running")]
    [InlineData(3, false, "Disabled")]
    [InlineData(0, true, "Unknown")]
    public void StatesReadAsWords(int state, bool enabled, string expected) =>
        Assert.Equal(expected, ScheduledTasks.DescribeState(state, enabled));

    [Fact]
    public void LastRunShowsTheExitCodeOrTheSchedulersWord()
    {
        var when = new DateTime(2027, 1, 4, 9, 41, 0);
        Assert.Equal("2027-01-04 09:41, Exit code 0", ScheduledTasks.DescribeLastRun(when, 0));
        Assert.Equal("2027-01-04 09:41, Exit code 2", ScheduledTasks.DescribeLastRun(when, 2));
        Assert.Equal("2027-01-04 09:41, Still running", ScheduledTasks.DescribeLastRun(when, 0x41301));
        Assert.Equal("Has not run yet", ScheduledTasks.DescribeLastRun(new DateTime(1999, 11, 30), 0x41303));
        Assert.Equal("2027-01-04 09:41, Result 0x80070005", ScheduledTasks.DescribeLastRun(when, unchecked((int)0x80070005)));
    }
}
