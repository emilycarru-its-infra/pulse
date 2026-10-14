using CommunityToolkit.Mvvm.ComponentModel;
using Microsoft.UI.Dispatching;
using Microsoft.UI.Xaml.Controls;
using PulseAgent.Core;

namespace PulseAgent.App.ViewModels;

/// <summary>
/// The Run tab: what the agent, running as SYSTEM, last saw and sent, read from its status.json
/// every two seconds. Send now signals the running agent, so it needs no elevation.
/// </summary>
public partial class RunViewModel : ObservableObject
{
    private readonly DispatcherQueueTimer timer;
    private string? sentBefore;

    [ObservableProperty] private string _seatText = "Unknown";
    [ObservableProperty] private string _seatReason = "";
    [ObservableProperty] private string _signedInText = "";
    [ObservableProperty] private string _lockedText = "";
    [ObservableProperty] private string _idleText = "";
    [ObservableProperty] private string _lastSentText = "";
    [ObservableProperty] private string _lastResultText = "";
    [ObservableProperty] private string _certificateText = "";
    [ObservableProperty] private string _updatedText = "";
    [ObservableProperty] private bool _isWaiting;
    [ObservableProperty] private bool _canSend = true;
    [ObservableProperty] private string _message = "";
    [ObservableProperty] private InfoBarSeverity _messageSeverity = InfoBarSeverity.Informational;

    public bool HasMessage => Message.Length > 0;
    partial void OnMessageChanged(string value) => OnPropertyChanged(nameof(HasMessage));

    public RunViewModel(DispatcherQueue queue)
    {
        timer = queue.CreateTimer();
        timer.Interval = TimeSpan.FromSeconds(2);
        timer.Tick += (_, _) => Refresh();
    }

    public void Start()
    {
        Refresh();
        timer.Start();
    }

    public void Stop() => timer.Stop();

    public void SendNow()
    {
        Message = "";
        if (!Agent.RequestSendNow())
        {
            Show("The agent is not running, so nothing was sent. Its scheduled task starts it at boot.", InfoBarSeverity.Warning);
            return;
        }
        sentBefore = AgentStatus.Read()?.LastSentAt;
        IsWaiting = true;
        CanSend = false;
    }

    private void Show(string text, InfoBarSeverity severity)
    {
        MessageSeverity = severity;
        Message = text;
    }

    private void Refresh()
    {
        var status = AgentStatus.Read();
        if (status is null)
        {
            SeatText = "Unknown";
            SeatReason = "The agent has not written its status yet. It runs as a scheduled task from boot.";
            UpdatedText = "";
            return;
        }

        (SeatText, SeatReason) = status.SeatState switch
        {
            "available" => ("Free", status.Active ? "No input for at least 15 minutes." : "Nobody is signed in."),
            "in_use" => ("In use", "Someone is signed in with input in the last 15 minutes."),
            _ => (status.SeatState, ""),
        };
        SignedInText = status.Active ? "Yes" : "No";
        LockedText = status.Active ? (status.Locked ? "Yes" : "No") : "—";
        IdleText = status.Active ? $"{Duration(status.IdleSeconds)} (from {status.IdleSource})" : "—";
        LastSentText = status.LastSentType is null ? "Nothing yet" : $"{status.LastSentType} at {Local(status.LastSentAt)}";
        LastResultText = status.LastResult ?? "—";
        CertificateText = status.Certificate is null ? "Not presented" : $"{status.Certificate}, expires {status.CertificateExpires}";
        UpdatedText = $"Agent checked at {Local(status.UpdatedAt)}";

        if (IsWaiting && status.LastSentAt != sentBefore)
        {
            IsWaiting = false;
            CanSend = true;
            Show(status.LastOk ? $"Sent: {status.LastResult}." : $"Not sent: {status.LastResult}.",
                status.LastOk ? InfoBarSeverity.Success : InfoBarSeverity.Error);
        }
    }

    private static string Local(string? utc) =>
        DateTimeOffset.TryParse(utc, out var at) ? at.ToLocalTime().ToString("HH:mm:ss") : "—";

    private static string Duration(int seconds) => seconds switch
    {
        < 60 => $"{seconds} s",
        < 3600 => $"{seconds / 60} min",
        _ => $"{seconds / 3600} h {seconds % 3600 / 60} min",
    };
}
