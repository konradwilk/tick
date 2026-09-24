using Microsoft.UI.Xaml;
using Microsoft.Windows.AppLifecycle;
namespace NonprofitHours;
public partial class App : Application
{
    private Window? window;
    public App() { InitializeComponent(); }
    protected override void OnLaunched(LaunchActivatedEventArgs args)
    {
        // Avoid concurrent writers to the same local session file.
        if (!AppInstance.FindOrRegisterForKey("NonprofitHours").IsCurrent) { Exit(); return; }
        window = new MainWindow();
        window.Activate();
    }
}
