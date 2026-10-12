using System.Runtime.InteropServices;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using PulseAgent.App.Views;
using PulseAgent.Core;

namespace PulseAgent.App;

public sealed partial class MainWindow : Window
{
    [DllImport("user32.dll")]
    private static extern uint GetDpiForWindow(IntPtr hwnd);

    public MainWindow()
    {
        InitializeComponent();

        Title = Identity.GuiName;
        AppTitle.Text = Identity.GuiName;

        // 1280 x 1060 DIP scaled by the monitor's DPI, kept inside 96% of the work area, and never
        // smaller than 900 x 640 DIP.
        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(this);
        var scale = GetDpiForWindow(hwnd) / 96.0;
        var work = Microsoft.UI.Windowing.DisplayArea.GetFromWindowId(
            AppWindow.Id, Microsoft.UI.Windowing.DisplayAreaFallback.Nearest).WorkArea;
        AppWindow.Resize(new Windows.Graphics.SizeInt32(
            Math.Min((int)(1280 * scale), (int)(work.Width * 0.96)),
            Math.Min((int)(1060 * scale), (int)(work.Height * 0.96))));
        if (AppWindow.Presenter is Microsoft.UI.Windowing.OverlappedPresenter presenter)
        {
            presenter.PreferredMinimumWidth = (int)(900 * scale);
            presenter.PreferredMinimumHeight = (int)(640 * scale);
        }

        AppWindow.SetIcon(Path.Combine(AppContext.BaseDirectory, "Assets", $"{Identity.IconName}.ico"));
        ExtendsContentIntoTitleBar = true;
        SetTitleBar(AppTitleBar);
        SystemBackdrop = new MicaBackdrop();

        // Prefs is the first tab; the elevated relaunch from Unlock passes --prefs as well.
        NavView.SelectedItem = NavView.MenuItems[0];
    }

    private void NavView_SelectionChanged(NavigationView sender, NavigationViewSelectionChangedEventArgs args)
    {
        if (args.SelectedItemContainer is not NavigationViewItem item) return;
        ContentFrame.Navigate(item.Tag?.ToString() switch
        {
            "run" => typeof(RunPage),
            "logs" => typeof(LogsPage),
            _ => typeof(PrefsPage),
        });
    }
}
