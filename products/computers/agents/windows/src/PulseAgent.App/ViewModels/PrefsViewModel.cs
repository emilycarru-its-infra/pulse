using System.Collections.ObjectModel;
using CommunityToolkit.Mvvm.ComponentModel;
using Microsoft.UI.Xaml.Media;
using PulseAgent.Core;

namespace PulseAgent.App.ViewModels;

/// <summary>
/// The Prefs tab. Every setting policy does not manage can be edited, and saves itself half a
/// second after the last edit. Settings live in HKLM, so an unelevated app hands the changed keys
/// to a copy of itself started through UAC, which asks for an administrator at that moment; an
/// elevated app writes them itself. A value set by policy (Intune or Group Policy) shows its policy
/// value in a disabled, grey control and is never written; one line at the top of the tab says so
/// when any is. The Services card lists the agent's scheduled tasks, read-only, one expandable row
/// each, and is hidden when the agent ships none.
/// </summary>
public partial class PrefsViewModel : ObservableObject
{
    private Timer? saveTimer;
    private bool loading;
    private bool saving;
    private bool saveAgain;
    private HashSet<string> managed = [];
    // The values as last loaded or saved, so an unelevated save sends only what changed.
    private Dictionary<string, object> saved = [];

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

    public enum SaveState { Idle, Saving, Saved, Failed }

    public ObservableCollection<ScheduledTaskStatus> Services { get; } = [];
    public bool HasServices { get; } = ScheduledTasks.AnyDefined;

    // Unelevated, the protected Secrets key cannot be read, so whether a key is saved is unknown.
    public string KeyPlaceholder => !IsElevated ? "Optional; enter a value to set or replace" : HasSavedKey ? "Saved; enter a new value to replace" : "Optional";
    public bool IsElevated { get; } = PrefsElevation.IsProcessElevated();

    // NumberBox.Value is a double.
    public double CheckIntervalValue { get => CheckInterval; set => CheckInterval = (int)value; }
    public double HeartbeatIntervalValue { get => HeartbeatInterval; set => HeartbeatInterval = (int)value; }

    private bool Locked(string key) => managed.Contains(key);
    private bool CanEdit(string key) => !Locked(key);

    /// <summary>Whether policy sets any key on this device, which shows the line about grey settings.</summary>
    public bool HasPolicySettings => managed.Count > 0;

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
        saved = Current();
        OnPropertyChanged(string.Empty);
        loading = false;
        LoadServices();
    }

    // Task Scheduler can take a moment to answer, so the card fills in after the settings.
    private async void LoadServices()
    {
        var tasks = await Task.Run(ScheduledTasks.Read);
        Services.Clear();
        foreach (var task in tasks) Services.Add(task);
    }

    private static readonly HashSet<string> settingProperties =
    [
        nameof(IngestUrl), nameof(IngestKey), nameof(UseDeviceCertificate),
        nameof(CheckInterval), nameof(HeartbeatInterval), nameof(VerboseLogging),
    ];

    protected override void OnPropertyChanged(System.ComponentModel.PropertyChangedEventArgs e)
    {
        base.OnPropertyChanged(e);
        if (loading || !settingProperties.Contains(e.PropertyName ?? "")) return;
        var queue = Microsoft.UI.Dispatching.DispatcherQueue.GetForCurrentThread();
        saveTimer?.Dispose();
        saveTimer = new Timer(_ => queue.TryEnqueue(Save), null, 500, Timeout.Infinite);
    }

    /// <summary>The settings as the controls hold them, keyed by setting name. The ingest key is
    /// in only when one has been typed.</summary>
    private Dictionary<string, object> Current()
    {
        var values = new Dictionary<string, object>
        {
            [SettingsStore.IngestUrl] = IngestUrl.Trim(),
            [SettingsStore.CheckIntervalSeconds] = CheckInterval,
            [SettingsStore.HeartbeatIntervalSeconds] = HeartbeatInterval,
            [SettingsStore.UseDeviceCertificate] = UseDeviceCertificate,
            [SettingsStore.VerboseLogging] = VerboseLogging,
        };
        if (IngestKey.Length > 0) values[SettingsStore.IngestKey] = IngestKey;
        return values;
    }

    private async void Save()
    {
        // A save already waiting on UAC picks up this edit when it finishes.
        if (saving)
        {
            saveAgain = true;
            return;
        }
        saving = true;
        SaveStatus = SaveState.Saving;
        try
        {
            var current = Current();
            if (IsElevated)
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
            }
            else
            {
                var changes = current
                    .Where(v => !managed.Contains(v.Key) && !(saved.TryGetValue(v.Key, out var was) && Equals(was, v.Value)))
                    .ToDictionary();
                if (changes.Count == 0)
                {
                    SaveStatus = SaveState.Idle;
                    return;
                }
                if (await ApplyElevatedAsync(changes) is { } error)
                {
                    // Show the fields as HKLM holds them again: nothing was written.
                    SaveError = error;
                    SaveStatus = SaveState.Failed;
                    Load();
                    return;
                }
            }
            saved = current;
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
        finally
        {
            saving = false;
            if (saveAgain)
            {
                saveAgain = false;
                Save();
            }
        }
    }

    /// <summary>Runs this app elevated in its hidden apply mode with the changed keys and waits for
    /// it. Null when it wrote them, else why not.</summary>
    private static async Task<string?> ApplyElevatedAsync(Dictionary<string, object> changes)
    {
        if (Environment.ProcessPath is not { Length: > 0 } exe) return "the app could not find its own executable.";
        try
        {
            return await PrefsElevation.RunElevatedApplyAsync(exe, changes) switch
            {
                PrefsElevation.Applied => null,
                PrefsElevation.Refused => "the change was refused; a setting may be set by policy, or the app is not installed under Program Files.",
                _ => "the settings could not be written.",
            };
        }
        catch (Exception ex) when (PrefsElevation.IsElevationCancelled(ex))
        {
            return "an administrator must approve the change.";
        }
    }
}
