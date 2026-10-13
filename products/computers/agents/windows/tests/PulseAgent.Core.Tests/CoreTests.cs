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

public class DeviceCertificateTests
{
    [Theory]
    [InlineData("CN=Microsoft Intune MDM Device CA", true)]
    [InlineData("cn=microsoft intune mdm device ca", true)]
    [InlineData("CN=Microsoft Intune Device Management Device CA", false)]
    [InlineData("CN=Microsoft Intune MDM Device CA Lookalike", false)]
    [InlineData("DC=net + DC=windows + CN=MS-Organization-Access + OU=00000000-0000-0000-0000-000000000000", false)]
    public void OnlyTheIntuneMdmDeviceCaIsAccepted(string issuer, bool expected) =>
        Assert.Equal(expected, DeviceCertificate.IsIssuedByCa(issuer));
}

public class ScheduledTaskTests
{
    private const string AgentXml = """
        <?xml version="1.0" encoding="UTF-16"?>
        <Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
          <RegistrationInfo>
            <Author>Example IT</Author>
            <Description>Reports whether this computer is free.</Description>
          </RegistrationInfo>
          <Principals>
            <Principal id="Author"><UserId>S-1-5-18</UserId><LogonType>ServiceAccount</LogonType><RunLevel>HighestAvailable</RunLevel></Principal>
          </Principals>
          <Settings><Hidden>false</Hidden></Settings>
          <Triggers><BootTrigger><Enabled>true</Enabled></BootTrigger></Triggers>
          <Actions Context="Author">
            <Exec>
              <Command>"C:\Program Files\Example\agent.exe"</Command>
              <Arguments>run</Arguments>
              <WorkingDirectory>C:\Program Files\Example</WorkingDirectory>
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

    private const string IdleXml = """
        <Task xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
          <Principals><Principal id="Author"><GroupId>S-1-5-32-545</GroupId><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
          <Settings><Hidden>true</Hidden></Settings>
          <Triggers><LogonTrigger><Enabled>true</Enabled></LogonTrigger></Triggers>
          <Actions><Exec><Command>C:\idle.exe</Command></Exec></Actions>
        </Task>
        """;

    private static readonly DateTime When = new(2027, 1, 4, 9, 41, 0);
    private static readonly DateTime Never = new(1899, 12, 30);

    private static TaskSnapshot Snapshot(string xml, bool enabled = true, int state = 3, int result = 0, DateTime? lastRun = null) =>
        new("Agent", @"\Agent", enabled, state, lastRun ?? When, result, Never, ScheduledTasks.ParseDefinition(xml.Trim()));

    private static string Detail(ScheduledTaskStatus status, string label) =>
        status.Details.Single(d => d.Label == label).Value;

    [Fact]
    public void BootTaskReadsItsDefinition()
    {
        var definition = ScheduledTasks.ParseDefinition(AgentXml.Trim());
        Assert.Equal("At startup", definition.Trigger);
        Assert.Equal(new TaskAction(@"C:\Program Files\Example\agent.exe", "run", @"C:\Program Files\Example"), Assert.Single(definition.Actions));
        Assert.Equal("SYSTEM", definition.RunAs);
        Assert.Equal("Highest privileges", definition.RunLevel);
        Assert.Equal("Example IT", definition.Author);
        Assert.Equal("Reports whether this computer is free.", definition.Description);
        Assert.False(definition.Hidden);
    }

    [Fact]
    public void EventTaskNamesTheEventAndSkipsADisabledTrigger()
    {
        var definition = ScheduledTasks.ParseDefinition(ShutdownXml);
        Assert.Equal("On event 1074 in the System log", definition.Trigger);
        Assert.Equal(@"C:\agent.exe", Assert.Single(definition.Actions).Program);
        Assert.Equal("The account that registered it", definition.RunAs);
        Assert.Equal("Standard privileges", definition.RunLevel);
        Assert.Equal("", definition.Author);
    }

    [Fact]
    public void GroupTaskRunsAsAnyMemberOfTheGroup()
    {
        var definition = ScheduledTasks.ParseDefinition(IdleXml);
        Assert.Equal("Any member of Users", definition.RunAs);
        Assert.Equal("At log on of any user", definition.Trigger);
        Assert.True(definition.Hidden);
    }

    [Fact]
    public void DetailCarriesTheReportMateFields()
    {
        var status = ScheduledTasks.Describe(Snapshot(AgentXml, state: 4, result: 0x41301));
        Assert.Equal("Running", status.State);
        Assert.Equal(StatusTone.Healthy, status.Tone);
        Assert.Equal(@"\Agent", Detail(status, "Path"));
        Assert.Equal(@"\", Detail(status, "Folder"));
        Assert.Equal("Yes", Detail(status, "Enabled"));
        Assert.Equal("No", Detail(status, "Hidden"));
        Assert.Equal("2027-01-04 09:41", Detail(status, "Last run"));
        Assert.Equal("0x00041301 (Still running)", Detail(status, "Last result"));
        Assert.Equal("None scheduled; it runs on its trigger", Detail(status, "Next run"));
        Assert.Equal("At startup", Detail(status, "Triggers"));
        Assert.Equal("run", Detail(status, "Arguments"));
        Assert.Equal(@"C:\Program Files\Example", Detail(status, "Starts in"));
        Assert.Equal("SYSTEM", Detail(status, "Run as"));
        Assert.Equal("Highest privileges", Detail(status, "Run level"));
        Assert.Equal("Example IT", Detail(status, "Author"));
        Assert.True(status.Details.Single(d => d.Label == "Program").Monospace);
        Assert.False(status.Details.Single(d => d.Label == "Run as").Monospace);
    }

    [Fact]
    public void ATaskThatHasNotRunHasNoResultLineAndAnEmptyAuthorIsLeftOut()
    {
        var status = ScheduledTasks.Describe(Snapshot(ShutdownXml, result: 0x41303, lastRun: new DateTime(1999, 11, 30)));
        Assert.Equal("Has not run yet", Detail(status, "Last run"));
        Assert.DoesNotContain(status.Details, d => d.Label is "Last result" or "Author" or "Arguments" or "Starts in");
        Assert.Equal(StatusTone.Healthy, status.Tone);
    }

    [Theory]
    [InlineData(true, 3, 0, StatusTone.Healthy)]
    [InlineData(true, 4, 0x41301, StatusTone.Healthy)]
    [InlineData(true, 3, 0x41306, StatusTone.Healthy)]
    [InlineData(true, 3, unchecked((int)0xC000013A), StatusTone.Healthy)]
    [InlineData(false, 3, 0, StatusTone.Inactive)]
    [InlineData(true, 1, 0, StatusTone.Inactive)]
    [InlineData(false, 3, 2, StatusTone.Inactive)]
    [InlineData(true, 3, 2, StatusTone.Failed)]
    [InlineData(true, 3, unchecked((int)0x80070005), StatusTone.Failed)]
    public void TheDotIsRedOnlyForAFailedRun(bool enabled, int state, int result, StatusTone expected) =>
        Assert.Equal(expected, ScheduledTasks.ToneOf(enabled, state, result));

    [Fact]
    public void ATaskStatusWithoutDetailIsGray()
    {
        var status = new ScheduledTaskStatus("Agent", "Not installed");
        Assert.Equal(StatusTone.Inactive, status.Tone);
        Assert.Empty(status.Details);
        Assert.Equal("Agent, Not installed", status.AccessibleName);
        Assert.Equal("Scheduled task", status.Summary);
    }

    [Fact]
    public void TheCollapsedRowSummarizesTriggerAndLastResult()
    {
        Assert.Equal("Scheduled task · At startup · Last result 0x0", ScheduledTasks.SummaryLine("At startup", true, 0));
        Assert.Equal("Scheduled task · At log on of any user · Last result 0x41306", ScheduledTasks.SummaryLine("At log on of any user", true, 0x41306));
        Assert.Equal("Scheduled task · On event 1074 in the System log · Has not run yet", ScheduledTasks.SummaryLine("On event 1074 in the System log", false, 0x41303));
        Assert.Equal("Scheduled task · Every 6 hours · Last result 0x80070005", ScheduledTasks.SummaryLine("Every 6 hours", true, unchecked((int)0x80070005)));
    }

    [Fact]
    public void DescribeFillsTheSummary() =>
        Assert.Equal("Scheduled task · At startup · Last result 0x2", ScheduledTasks.Describe(Snapshot(AgentXml, result: 2)).Summary);

    [Theory]
    [InlineData(@"\Agent", @"\")]
    [InlineData(@"\Vendor\Agent", @"\Vendor")]
    [InlineData("Agent", @"\")]
    public void FolderIsThePathWithoutTheName(string path, string expected) =>
        Assert.Equal(expected, ScheduledTasks.FolderOf(path));

    [Theory]
    [InlineData("PT6H", "6 hours")]
    [InlineData("PT1H", "hour")]
    [InlineData("PT90M", "90 minutes")]
    [InlineData("P1D", "day")]
    public void IntervalsReadAsWords(string xml, string expected) =>
        Assert.Equal(expected, ScheduledTasks.DescribeInterval(System.Xml.XmlConvert.ToTimeSpan(xml)));

    [Theory]
    [InlineData(3, true, "Ready, not running")]
    [InlineData(4, true, "Running")]
    [InlineData(3, false, "Disabled")]
    [InlineData(0, true, "Unknown")]
    public void StatesReadAsWords(int state, bool enabled, string expected) =>
        Assert.Equal(expected, ScheduledTasks.DescribeState(state, enabled));

    [Fact]
    public void ResultsReadAsHexAndMeaning()
    {
        Assert.Equal("0x00000000 (Exit code 0, success)", ScheduledTasks.DescribeResult(0));
        Assert.Equal("0x00000002 (Exit code 2)", ScheduledTasks.DescribeResult(2));
        Assert.Equal("0x00041303 (Has not run yet)", ScheduledTasks.DescribeResult(0x41303));
        Assert.Equal("0xC000013A (Ended when Windows shut down)", ScheduledTasks.DescribeResult(unchecked((int)0xC000013A)));
        Assert.Equal("0xDEADBEEF (Unrecognized result)", ScheduledTasks.DescribeResult(unchecked((int)0xDEADBEEF)));
        // A wrapped Win32 error takes the system's message, whatever the display language.
        var denied = ScheduledTasks.DescribeResult(unchecked((int)0x80070005));
        Assert.StartsWith("0x80070005 (", denied);
        Assert.DoesNotContain("Unrecognized", denied);
    }
}

public class ApplySettingsTests
{
    private static readonly HashSet<string> NoPolicy = [];
    private static readonly string[] Roots = [@"C:\Program Files", @"C:\Program Files (x86)"];
    private const string Installed = @"C:\Program Files\Example\Example App.exe";

    [Fact]
    public async Task ChangedKeysRoundTripThroughAFrame()
    {
        var changes = new Dictionary<string, object>
        {
            [SettingsStore.IngestUrl] = "https://status.example.edu/api/ingest",
            [SettingsStore.IngestKey] = "s3cret",
            [SettingsStore.CheckIntervalSeconds] = 30,
            [SettingsStore.VerboseLogging] = true,
        };
        using var stream = new MemoryStream();
        await PrefsElevation.WriteFrameAsync(stream, System.Text.Json.JsonSerializer.Serialize(changes));
        stream.Position = 0;
        var values = PrefsElevation.Validate((await PrefsElevation.ReadFrameAsync(stream))!, NoPolicy, out var error);
        Assert.Equal("", error);
        Assert.Equal(changes, values);
    }

    [Fact]
    public void OnlyThePipeNameGoesOnTheCommandLine()
    {
        var name = PrefsElevation.NewPipeName();
        Assert.True(PrefsElevation.IsPipeName(name));
        var start = PrefsElevation.BuildElevatedApply(Installed, name);
        Assert.Equal("runas", start.Verb);
        Assert.Equal($"{PrefsElevation.ApplyArgument} {name}", start.Arguments);
        Assert.Equal(name, PrefsElevation.ApplyPipeName(start.Arguments.Split(' ')));
    }

    [Theory]
    [InlineData("")]
    [InlineData("eyJJbmdlc3RVcmwiOiJ4In0=")]
    [InlineData(@"..\..\pipe\other")]
    public void APayloadOrStrangeNameIsNotAPipeName(string name) => Assert.False(PrefsElevation.IsPipeName(name));

    [Fact]
    public void OnlyTheApplySwitchStartsTheApplyMode()
    {
        Assert.Null(PrefsElevation.ApplyPipeName([]));
        Assert.Null(PrefsElevation.ApplyPipeName(["--prefs"]));
        Assert.Equal("", PrefsElevation.ApplyPipeName([PrefsElevation.ApplyArgument]));
    }

    [Fact]
    public async Task ShortOrOversizedFramesAreRefused()
    {
        Assert.Null(await PrefsElevation.ReadFrameAsync(new MemoryStream([5, 0, 0, 0, (byte)'{'])));
        Assert.Null(await PrefsElevation.ReadFrameAsync(new MemoryStream([0, 0, 0, 0])));
        Assert.Null(await PrefsElevation.ReadFrameAsync(new MemoryStream([0xFF, 0xFF, 0xFF, 0x7F])));
        Assert.Null(await PrefsElevation.ReadFrameAsync(new MemoryStream([1, 0])));
    }

    [Fact]
    public void TheSameAppUnderProgramFilesIsTrusted()
    {
        Assert.True(PrefsElevation.IsTrustedServer(Installed, Installed, Roots));
        Assert.True(PrefsElevation.IsTrustedServer(Installed.ToUpperInvariant(), Installed, Roots));
    }

    [Theory]
    [InlineData(@"C:\Users\me\Downloads\evil.exe", Installed)]
    [InlineData(@"C:\Program Files\Example\Other.exe", Installed)]
    [InlineData(null, Installed)]
    [InlineData(@"C:\Users\me\app\Example App.exe", @"C:\Users\me\app\Example App.exe")]
    [InlineData(@"C:\Program Files Evil\Example App.exe", @"C:\Program Files Evil\Example App.exe")]
    [InlineData(@"C:\Program Files\..\Users\me\a.exe", @"C:\Program Files\..\Users\me\a.exe")]
    [InlineData(@"\\server\share\Program Files\a.exe", @"\\server\share\Program Files\a.exe")]
    public void AnyOtherServerOrPlaceIsNot(string? server, string own) =>
        Assert.False(PrefsElevation.IsTrustedServer(server, own, Roots));

    [Fact]
    public void IntervalsAreClampedToTheirRanges()
    {
        var values = PrefsElevation.Validate("""{"CheckIntervalSeconds":1,"HeartbeatIntervalSeconds":99999}""", NoPolicy, out _);
        Assert.Equal(5, values![SettingsStore.CheckIntervalSeconds]);
        Assert.Equal(3600, values[SettingsStore.HeartbeatIntervalSeconds]);
    }

    [Theory]
    [InlineData("""{"Nonsense":1}""")]
    [InlineData("""{"CheckIntervalSeconds":"thirty"}""")]
    [InlineData("""{"VerboseLogging":1}""")]
    [InlineData("""{"IngestKey":""}""")]
    [InlineData("""{}""")]
    [InlineData("""[1,2]""")]
    [InlineData("""not json""")]
    public void BadPayloadsAreRefused(string json)
    {
        Assert.Null(PrefsElevation.Validate(json, NoPolicy, out var error));
        Assert.NotEqual("", error);
    }

    [Fact]
    public void APolicyKeyIsNeverWritten()
    {
        HashSet<string> managed = [SettingsStore.IngestUrl];
        Assert.Null(PrefsElevation.Validate("""{"ingesturl":"https://x.example"}""", managed, out var error));
        Assert.Contains("policy", error);
    }
}
