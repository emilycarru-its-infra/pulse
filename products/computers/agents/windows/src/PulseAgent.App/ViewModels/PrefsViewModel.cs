using CommunityToolkit.Mvvm.ComponentModel;
using Microsoft.UI.Xaml.Media;
using PulseAgent.Core;

namespace PulseAgent.App.ViewModels;

/// <summary>
/// The Prefs tab. Settings live in HKLM, so the tab is read-only unless this process is elevated;
/// Unlock relaunches the app elevated on this tab. A value set by policy (Intune or Group Policy)
/// shows its managed value, greyed, with a lock and the word Managed, and is never written.
/// Elevated, every other change saves itself half a second after the last edit.
/// </summary>
public partial class PrefsViewModel : ObservableObject
{
    private Timer? saveTimer;
    private bool loading;
    private HashSet<string> managed = [];

    [ObservableProperty] private string _ingestUrl = "";
    [ObservableProperty] private string _ingestKey = "";
    [ObservableProperty] private bool _hasSavedKey;
    [ObservableProperty] private bool _useDeviceCertificate = true;
    [ObservableProperty] private int _checkInterval = AgentSettings.DefaultCheckSeconds;
    [ObservableProperty] private int _heartbeatInterval = AgentSettings.DefaultHeartbeatSeconds;
    [ObservableProperty] private bool _verboseLogging;
    [ObservableProperty] private string _certificateText = "";
    [ObservableProperty] private string _deviceText = "";
    [ObservableProperty] private SaveState _saveStatus = SaveState.Idle;
    [ObservableProperty] private string _saveError = "";
    [ObservableProperty] private string _unlockError = "";

    public enum SaveState { Idle, Saving, Saved, Failed }

    public string VersionDisplay => Identity.VersionDisplay;
    public string KeyPlaceholder => HasSavedKey ? "Saved; enter a new value to replace" : "Optional";
    public bool IsElevated { get; } = PrefsElevation.IsProcessElevated();
    public bool IsReadOnly => !IsElevated;
    public bool HasUnlockError => UnlockError.Length > 0;

    // NumberBox.Value is a double.
    public double CheckIntervalValue { get => CheckInterval; set => CheckInterval = (int)value; }
    public double HeartbeatIntervalValue { get => HeartbeatInterval; set => HeartbeatInterval = (int)value; }

    private bool Locked(string key) => managed.Contains(key);
    private bool CanEdit(string key) => PrefsElevation.CanEdit(IsElevated, Locked(key));

    public bool IsIngestUrlLocked => Locked(SettingsStore.IngestUrl);
    public bool IsIngestKeyLocked => Locked(SettingsStore.IngestKey);
    public bool IsUseDeviceCertificateLocked => Locked(SettingsStore.UseDeviceCertificate);
    public bool IsCheckIntervalLocked => Locked(SettingsStore.CheckIntervalSeconds);
    public bool IsHeartbeatIntervalLocked => Locked(SettingsStore.HeartbeatIntervalSeconds);
    public bool IsVerboseLoggingLocked => Locked(SettingsStore.VerboseLogging);

    public bool CanEditIngestUrl => CanEdit(SettingsStore.IngestUrl);
    public bool CanEditIngestKey => CanEdit(SettingsStore.IngestKey);
    public bool CanEditUseDeviceCertificate => CanEdit(SettingsStore.UseDeviceCertificate);
    public bool CanEditCheckInterval => CanEdit(SettingsStore.CheckIntervalSeconds);
    public bool CanEditHeartbeatInterval => CanEdit(SettingsStore.HeartbeatIntervalSeconds);
    public bool CanEditVerboseLogging => CanEdit(SettingsStore.VerboseLogging);

    public bool IsSaveStatusVisible => SaveStatus != SaveState.Idle;
    public string SaveStatusGlyph => SaveStatus switch
    {
        SaveState.Saving => "",
        SaveState.Saved => "",
        SaveState.Failed => "",
        _ => "",
    };
    public string SaveStatusMessage => SaveStatus switch
    {
        SaveState.Saving => "Saving…",
        SaveState.Saved => "Saved",
        SaveState.Failed => $"Not saved: {SaveError}",
        _ => "",
    };
    public Brush SaveStatusBrush => (Brush)Microsoft.UI.Xaml.Application.Current.Resources[SaveStatus switch
    {
        SaveState.Saved => "SystemFillColorSuccessBrush",
        SaveState.Failed => "SystemFillColorCriticalBrush",
        _ => "TextFillColorSecondaryBrush",
    }];

    partial void OnSaveStatusChanged(SaveState value)
    {
        OnPropertyChanged(nameof(IsSaveStatusVisible));
        OnPropertyChanged(nameof(SaveStatusGlyph));
        OnPropertyChanged(nameof(SaveStatusMessage));
        OnPropertyChanged(nameof(SaveStatusBrush));
    }

    partial void OnHasSavedKeyChanged(bool value) => OnPropertyChanged(nameof(KeyPlaceholder));
    partial void OnUnlockErrorChanged(string value) => OnPropertyChanged(nameof(HasUnlockError));
    partial void OnCheckIntervalChanged(int value) => OnPropertyChanged(nameof(CheckIntervalValue));
    partial void OnHeartbeatIntervalChanged(int value) => OnPropertyChanged(nameof(HeartbeatIntervalValue));

    public void Load()
    {
        loading = true;
        var settings = SettingsStore.Load();
        managed = SettingsStore.ManagedKeys();
        IngestUrl = settings.IngestUrl ?? "";
        HasSavedKey = !string.IsNullOrEmpty(settings.IngestKey);
        IngestKey = "";
        UseDeviceCertificate = settings.UseDeviceCertificate;
        CheckInterval = settings.CheckIntervalSeconds;
        HeartbeatInterval = settings.HeartbeatIntervalSeconds;
        VerboseLogging = settings.VerboseLogging;
        var cert = DeviceCertificate.Find();
        CertificateText = cert is null
            ? "No device certificate found. The computer may not be joined to Entra."
            : $"{DeviceCertificate.DeviceId(cert)}\nExpires {cert.NotAfter:yyyy-MM-dd}";
        DeviceText = $"{Device.Hostname}\nSerial {Device.Serial}";
        OnPropertyChanged(string.Empty);
        loading = false;
    }

    /// <summary>Relaunches elevated through UAC on this tab. True when the elevated copy started.</summary>
    public bool TryRelaunchElevated()
    {
        UnlockError = "";
        try
        {
            if (Environment.ProcessPath is not { Length: > 0 } exe)
            {
                UnlockError = "Could not find the app's own executable to relaunch.";
                return false;
            }
            using var process = System.Diagnostics.Process.Start(PrefsElevation.BuildElevatedRelaunch(exe));
            return process is not null;
        }
        catch (Exception ex) when (PrefsElevation.IsElevationCancelled(ex))
        {
            return false;
        }
        catch (Exception ex)
        {
            UnlockError = $"Could not relaunch as administrator: {ex.Message}";
            return false;
        }
    }

    private static readonly HashSet<string> settingProperties =
    [
        nameof(IngestUrl), nameof(IngestKey), nameof(UseDeviceCertificate),
        nameof(CheckInterval), nameof(HeartbeatInterval), nameof(VerboseLogging),
    ];

    protected override void OnPropertyChanged(System.ComponentModel.PropertyChangedEventArgs e)
    {
        base.OnPropertyChanged(e);
        if (loading || !IsElevated || !settingProperties.Contains(e.PropertyName ?? "")) return;
        var queue = Microsoft.UI.Dispatching.DispatcherQueue.GetForCurrentThread();
        saveTimer?.Dispose();
        saveTimer = new Timer(_ => queue.TryEnqueue(Save), null, 500, Timeout.Infinite);
    }

    private async void Save()
    {
        SaveStatus = SaveState.Saving;
        try
        {
            SettingsStore.Save(new AgentSettings
            {
                IngestUrl = IngestUrl.Trim(),
                IngestKey = IngestKey,
                UseDeviceCertificate = UseDeviceCertificate,
                CheckIntervalSeconds = CheckInterval,
                HeartbeatIntervalSeconds = HeartbeatInterval,
                VerboseLogging = VerboseLogging,
            }, managed);
            if (IngestKey.Length > 0) HasSavedKey = true;
            SaveStatus = SaveState.Saved;
            await Task.Delay(2500);
            if (SaveStatus == SaveState.Saved) SaveStatus = SaveState.Idle;
        }
        catch (Exception ex)
        {
            SaveError = ex.Message;
            SaveStatus = SaveState.Failed;
        }
    }
}
