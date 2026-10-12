using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Documents;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Navigation;
using PulseAgent.App.ViewModels;

namespace PulseAgent.App.Views;

public sealed partial class LogsPage : Page
{
    private readonly LogsViewModel vm = new();
    private readonly Microsoft.UI.Dispatching.DispatcherQueueTimer follow;

    public LogsPage()
    {
        InitializeComponent();
        vm.PropertyChanged += (_, e) => { if (e.PropertyName == nameof(LogsViewModel.FilteredLines)) Render(); };
        follow = DispatcherQueue.CreateTimer();
        follow.Interval = TimeSpan.FromSeconds(2);
        follow.Tick += (_, _) => vm.ReloadIfChanged();
        Refresh();
    }

    protected override void OnNavigatedTo(NavigationEventArgs e)
    {
        base.OnNavigatedTo(e);
        if (FollowToggle.IsOn) follow.Start();
    }

    protected override void OnNavigatedFrom(NavigationEventArgs e)
    {
        base.OnNavigatedFrom(e);
        follow.Stop();
    }

    private void Refresh()
    {
        vm.Refresh();
        LogFileList.ItemsSource = null;
        LogFileList.ItemsSource = vm.LogFiles;
        LogFileList.SelectedItem = vm.SelectedLog;
        Render();
    }

    private void LogFileList_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (LogFileList.SelectedItem is LogsViewModel.LogFile file) vm.SelectedLog = file;
    }

    private void FilterBox_TextChanged(object sender, TextChangedEventArgs e) => vm.FilterText = FilterBox.Text;
    private void OpenEditor_Click(object sender, RoutedEventArgs e) => vm.OpenInEditor();
    private void OpenFolder_Click(object sender, RoutedEventArgs e) => vm.OpenFolder();
    private void Refresh_Click(object sender, RoutedEventArgs e) => Refresh();

    private void Follow_Toggled(object sender, RoutedEventArgs e)
    {
        if (FollowToggle.IsOn) follow.Start(); else follow.Stop();
    }

    private void Render()
    {
        EmptyState.Visibility = vm.SelectedLog is null ? Visibility.Visible : Visibility.Collapsed;
        OpenEditorBtn.IsEnabled = vm.SelectedLog is not null;
        LogOutput.Blocks.Clear();
        foreach (var line in vm.FilteredLines)
        {
            var paragraph = new Paragraph { Foreground = BrushFor(line.Color), Margin = new Thickness(0, 1, 0, 1) };
            paragraph.Inlines.Add(new Run { Text = line.Text });
            LogOutput.Blocks.Add(paragraph);
        }
        if (FollowToggle.IsOn) LogScroller.ChangeView(null, double.MaxValue, null, disableAnimation: true);
    }

    private static Brush BrushFor(LogsViewModel.LogLineColor color) => color switch
    {
        LogsViewModel.LogLineColor.Error => new SolidColorBrush(Microsoft.UI.Colors.IndianRed),
        LogsViewModel.LogLineColor.Warning => new SolidColorBrush(Microsoft.UI.Colors.Goldenrod),
        LogsViewModel.LogLineColor.Debug => new SolidColorBrush(Windows.UI.Color.FromArgb(204, 128, 128, 128)),
        _ => (Brush)Application.Current.Resources["TextFillColorPrimaryBrush"],
    };
}
