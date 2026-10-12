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
