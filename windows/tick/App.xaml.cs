using Microsoft.UI.Xaml;
using Microsoft.Windows.AppLifecycle;
namespace Tick;
public partial class App : Application
{
    private Window? window;
    private TrayIcon? trayIcon;
    private AppInstance? instance;
    private bool quitting;
    public App() { InitializeComponent(); }
    protected override async void OnLaunched(LaunchActivatedEventArgs args)
    {
        // Avoid concurrent writers to the same local session file.
        instance = AppInstance.FindOrRegisterForKey("NonprofitHours");
        if (!instance.IsCurrent)
        {
            var activation = AppInstance.GetCurrent().GetActivatedEventArgs();
            await Task.Run(async () => await instance.RedirectActivationToAsync(activation));
            Exit();
            return;
        }
        window = new MainWindow();
        instance.Activated += OnActivated;
        trayIcon = new TrayIcon(ShowWindow, Quit);
        window.AppWindow.Closing += (_, closing) =>
        {
            if (quitting) return;
            closing.Cancel = true;
            window.AppWindow.Hide();
        };
        window.Closed += (_, _) =>
        {
            trayIcon?.Dispose();
            trayIcon = null;
            instance.Activated -= OnActivated;
            instance.UnregisterKey();
        };
        window.Activate();
    }

    private void OnActivated(object? sender, AppActivationArguments args) =>
        window?.DispatcherQueue.TryEnqueue(ShowWindow);

    private void ShowWindow()
    {
        if (quitting || window is null) return;
        window.AppWindow.Show();
        if (window.AppWindow.Presenter is Microsoft.UI.Windowing.OverlappedPresenter presenter &&
            presenter.State == Microsoft.UI.Windowing.OverlappedPresenterState.Minimized)
            presenter.Restore();
        window.Activate();
    }

    private void Quit()
    {
        quitting = true;
        window?.Close();
        Exit();
    }
}
