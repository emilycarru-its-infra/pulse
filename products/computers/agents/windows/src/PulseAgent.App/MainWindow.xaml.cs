using System.Runtime.InteropServices;
using Microsoft.UI.Input;
using Microsoft.UI.Windowing;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Input;
using Microsoft.UI.Xaml.Media;
using PulseAgent.App.Views;
using PulseAgent.Core;
using Windows.System;

namespace PulseAgent.App;

public sealed partial class MainWindow : Window
{
    [DllImport("user32.dll")]
    private static extern uint GetDpiForWindow(IntPtr hwnd);

    public MainWindow()
    {
        InitializeComponent();

        Title = Identity.GuiName;
        VersionText.Text = Identity.VersionDisplay;

        // 1100 x 900 DIP scaled by the monitor's DPI, kept inside 96% of the work area, and never
        // smaller than 900 x 640 DIP.
        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(this);
        var scale = GetDpiForWindow(hwnd) / 96.0;
        var work = DisplayArea.GetFromWindowId(AppWindow.Id, DisplayAreaFallback.Nearest).WorkArea;
        AppWindow.Resize(new Windows.Graphics.SizeInt32(
            Math.Min((int)(1100 * scale), (int)(work.Width * 0.96)),
            Math.Min((int)(900 * scale), (int)(work.Height * 0.96))));
        if (AppWindow.Presenter is OverlappedPresenter presenter)
        {
            presenter.PreferredMinimumWidth = (int)(900 * scale);
            presenter.PreferredMinimumHeight = (int)(640 * scale);
        }

        AppWindow.SetIcon(Path.Combine(AppContext.BaseDirectory, "Assets", $"{Identity.IconName}.ico"));
        ExtendsContentIntoTitleBar = true;
        SetTitleBar(AppTitleBar);
        // The tall caption buttons match the 48 DIP bar the selector sits in.
        AppWindow.TitleBar.PreferredHeightOption = TitleBarHeightOption.Tall;
        AppTitleBar.SizeChanged += (_, _) => UpdatePassthrough();
        SystemBackdrop = new MicaBackdrop();

        // Ctrl+1, 2 and 3 switch tabs, in the order they appear.
        for (var i = 0; i < Tabs.Items.Count; i++)
        {
            var item = Tabs.Items[i];
            var accelerator = new KeyboardAccelerator { Key = VirtualKey.Number1 + i, Modifiers = VirtualKeyModifiers.Control };
            accelerator.Invoked += (_, e) => { Tabs.SelectedItem = item; e.Handled = true; };
            ((UIElement)Content).KeyboardAccelerators.Add(accelerator);
        }

        // Prefs is the first tab; the elevated relaunch from Unlock passes --prefs as well.
        Tabs.SelectedItem = Tabs.Items[0];
    }

    private void Tabs_SelectionChanged(SelectorBar sender, SelectorBarSelectionChangedEventArgs args)
    {
        ContentFrame.Navigate(sender.SelectedItem?.Tag?.ToString() switch
        {
            "run" => typeof(RunPage),
            "logs" => typeof(LogsPage),
            _ => typeof(PrefsPage),
        });
    }

    private void Tabs_SizeChanged(object sender, SizeChangedEventArgs e) => UpdatePassthrough();

    // The title bar is a drag region, which swallows clicks; the selector's rectangle, in physical
    // pixels, is handed back to the content so its items can be clicked.
    private void UpdatePassthrough()
    {
        if (Tabs.XamlRoot is not { } root) return;
        var scale = root.RasterizationScale;
        var bounds = Tabs.TransformToVisual(null).TransformBounds(new Windows.Foundation.Rect(0, 0, Tabs.ActualWidth, Tabs.ActualHeight));
        InputNonClientPointerSource.GetForWindowId(AppWindow.Id).SetRegionRects(NonClientRegionKind.Passthrough,
        [
            new Windows.Graphics.RectInt32(
                (int)Math.Round(bounds.X * scale), (int)Math.Round(bounds.Y * scale),
                (int)Math.Round(bounds.Width * scale), (int)Math.Round(bounds.Height * scale)),
        ]);
    }
}
