using HoursCore;
using Microsoft.UI;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Windows.Storage.Pickers;
namespace Tick;
public sealed partial class MainWindow : Window
{
    private Tracker? tracker;
    private readonly StorageLocation location = new(
        Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "NonprofitHours", "location.json"),
        Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "NonprofitHours", "tick.json"));
    private readonly DispatcherTimer timer = new() { Interval = TimeSpan.FromSeconds(1) };
    public MainWindow()
    {
        InitializeComponent();
        AppWindow.Resize(new Windows.Graphics.SizeInt32(1100, 800));
        ReportDate.Date = DateTimeOffset.Now;
        timer.Tick += (_, _) => UpdateClock();
        timer.Start();
        Closed += (_, _) => timer.Stop();
        try
        {
            tracker = location.Open();
            Refresh();
            Nonprofits.SelectedItem = tracker.State.Nonprofits.FirstOrDefault(n => n.Id == tracker.State.Active?.ProjectId) ?? tracker.State.Nonprofits.FirstOrDefault();
            Notes.Text = tracker.State.Active?.Notes ?? "";

        }
        catch (Exception e)
        {
            Nonprofits.IsEnabled = Notes.IsEnabled = NewName.IsEnabled = AddButton.IsEnabled =
                Toggle.IsEnabled = ExportButton.IsEnabled = CopyButton.IsEnabled = false;
            if (e is FileNotFoundException or DirectoryNotFoundException)
            {
                ErrorText.Text = "Choose where to save tick.json (Settings → Data location).";
                ((FrameworkElement)Content).Loaded += PromptForDataLocation;
            }
            else ErrorText.Text = "Could not load saved hours. Your file was not changed. " + e.Message;
        }
    }
    private void PromptForDataLocation(object sender, RoutedEventArgs args)
    {
        ((FrameworkElement)Content).Loaded -= PromptForDataLocation;
        ChooseDataLocation(sender, args);
    }
    private void Perform(Action action)
    {
        try { action(); ErrorText.Text = ""; Refresh(); }
        catch (Exception e) { if (tracker != null) Refresh(); ErrorText.Text = e.Message; }
    }
    private void AddNonprofit(object sender, RoutedEventArgs args) => Perform(() =>
    {
        var id = tracker!.AddNonprofit(NewName.Text);
        NewName.Text = "";
        Refresh();
        Nonprofits.SelectedItem = tracker.State.Nonprofits.First(n => n.Id == id);
    });
    private void ToggleTracking(object sender, RoutedEventArgs args) => Perform(() =>
    {
        if (tracker!.State.Active != null) { tracker.Stop(); Notes.Text = ""; }
        else if (Nonprofits.SelectedItem is Nonprofit nonprofit) tracker.Start(nonprofit.Id, Notes.Text);
        else throw new InvalidOperationException("Select a project first.");
    });
    private void Refresh()
    {
        Toggle.IsEnabled = true;
        DataLocation.Text = Path.GetDirectoryName(location.CurrentPath);
        var state = tracker!.State;
        FirstRun.Visibility = state.Nonprofits.Length == 0 ? Visibility.Visible : Visibility.Collapsed;
        EmptyHistory.Visibility = state.Sessions.Length == 0 ? Visibility.Visible : Visibility.Collapsed;
        var selected = (Nonprofits.SelectedItem as Nonprofit)?.Id;
        Nonprofits.ItemsSource = state.Nonprofits;
        Nonprofits.SelectedItem = state.Nonprofits.FirstOrDefault(n => n.Id == selected);
        var active = state.Active != null;
        Nonprofits.IsEnabled = Notes.IsEnabled = NewName.IsEnabled = AddButton.IsEnabled = !active;
        Toggle.Content = active ? "Stop" : "Start";
        Toggle.Background = new SolidColorBrush(active ? Colors.Firebrick : Colors.ForestGreen);
        Total.Text = $"Completed: {state.Sessions.Sum(s => s.DurationSeconds ?? 0) / 3600.0:F2} hours";
        UpdateReport();
        History.ItemsSource = state.Sessions.OrderByDescending(s => s.StartTimeUtc).Select(s => new HistoryEntry(s.SessionId,
            $"{s.Project} — {s.StartTimeUtc.ToLocalTime():g}\n{(s.DurationSeconds is long seconds ? Elapsed(seconds) : "In progress")}\n{s.Notes}", s.EndTimeUtc != null,
            s.EndTimeUtc != null && s.DurationSeconds is >= 0 and < 60 ? Visibility.Visible : Visibility.Collapsed)).ToArray();
        UpdateClock();
    }
    public record HistoryEntry(Guid SessionId, string Summary, bool CanEdit, Visibility DeleteVisibility);
    private void DeleteSession(object sender, RoutedEventArgs args)
    {
        if (tracker != null && sender is Button { Tag: Guid id }) Perform(() => tracker.DeleteSession(id));
    }
    private async void AddManualSession(object sender, RoutedEventArgs args)
    {
        if (tracker == null) return;
        var nonprofit = new ComboBox { Header = "Project", DisplayMemberPath = "Name", ItemsSource = tracker.State.Nonprofits,
            SelectedItem = Nonprofits.SelectedItem ?? tracker.State.Nonprofits.FirstOrDefault(), HorizontalAlignment = HorizontalAlignment.Stretch };
        var activity = new TextBox { Header = "What did you work on?", AcceptsReturn = true, TextWrapping = TextWrapping.Wrap };
        var current = DateTime.Now;
        var start = current.Date.AddHours(current.Hour).AddMinutes(current.Minute).AddHours(-1);
        var end = start.AddMinutes(15);
        var startDate = new CalendarDatePicker { Header = "Start date", Date = start };
        var startTime = new TimePicker { Header = "Start time", Time = start.TimeOfDay };
        var endDate = new CalendarDatePicker { Header = "End date", Date = end };
        var endTime = new TimePicker { Header = "End time", Time = end.TimeOfDay };
        var endEdited = false;
        var updatingEnd = false;
        void UpdateDefaultEnd()
        {
            if (endEdited || startDate.Date == null || startTime.SelectedTime == null) return;
            var suggested = (startDate.Date.Value.Date + startTime.Time).AddMinutes(15);
            updatingEnd = true;
            endDate.Date = suggested;
            endTime.Time = suggested.TimeOfDay;
            updatingEnd = false;
        }
        startDate.DateChanged += (_, _) => UpdateDefaultEnd();
        startTime.TimeChanged += (_, _) => UpdateDefaultEnd();
        endDate.DateChanged += (_, _) => { if (!updatingEnd) endEdited = true; };
        endTime.TimeChanged += (_, _) => { if (!updatingEnd) endEdited = true; };
        var error = new TextBlock { TextWrapping = TextWrapping.Wrap, Foreground = new SolidColorBrush(Colors.Firebrick) };
        var content = new StackPanel { Spacing = 12 };
        foreach (var control in new UIElement[] { nonprofit, activity, new TextBlock { Text = "Times use your local timezone." }, startDate, startTime, endDate, endTime, error }) content.Children.Add(control);
        var dialog = new ContentDialog { XamlRoot = Controls.XamlRoot, Title = "Add session by hand",
            Content = new ScrollViewer { Content = content, MaxHeight = 450 }, PrimaryButtonText = "Save", CloseButtonText = "Cancel" };
        dialog.PrimaryButtonClick += (_, eventArgs) =>
        {
            try
            {
                if (nonprofit.SelectedItem is not Nonprofit selected) throw new InvalidOperationException("Select a project. Add one in Settings first if needed.");
                static DateTimeOffset LocalTime(CalendarDatePicker date, TimePicker time)
                {
                    if (date.Date == null || time.SelectedTime == null) throw new InvalidOperationException("Enter both dates and times.");
                    var value = DateTime.SpecifyKind(date.Date.Value.Date + time.Time, DateTimeKind.Unspecified);
                    if (TimeZoneInfo.Local.IsInvalidTime(value)) throw new InvalidOperationException("This local time does not exist due to a clock change.");
                    if (TimeZoneInfo.Local.IsAmbiguousTime(value)) throw new InvalidOperationException("This local time occurs twice due to a clock change. Choose an unambiguous time.");
                    return new DateTimeOffset(value, TimeZoneInfo.Local.GetUtcOffset(value));
                }
                tracker.AddSession(selected.Id, activity.Text, LocalTime(startDate, startTime), LocalTime(endDate, endTime));
                ErrorText.Text = "";
                Refresh();
            }
            catch (Exception e) { eventArgs.Cancel = true; error.Text = e.Message; }
        };
        await dialog.ShowAsync();
    }
    private async void EditTimes(object sender, RoutedEventArgs args)
    {
        if (tracker == null || sender is not Button { Tag: Guid sessionId }) return;
        var session = tracker.State.Sessions.FirstOrDefault(s => s.SessionId == sessionId);
        if (session?.EndTimeUtc == null) return;
        var start = session.StartTimeUtc.ToLocalTime();
        var end = session.EndTimeUtc.Value.ToLocalTime();
        var startDate = new CalendarDatePicker { Header = "Start date", Date = start };
        var startTime = new TimePicker { Header = "Start time", Time = start.TimeOfDay };
        var endDate = new CalendarDatePicker { Header = "End date", Date = end };
        var endTime = new TimePicker { Header = "End time", Time = end.TimeOfDay };
        var error = new TextBlock { TextWrapping = TextWrapping.Wrap, Foreground = new SolidColorBrush(Colors.Firebrick) };
        var content = new StackPanel { Spacing = 12 };
        foreach (var control in new UIElement[] { new TextBlock { Text = session.Project },
            new TextBlock { Text = "Times use your local timezone." }, startDate, startTime, endDate, endTime, error }) content.Children.Add(control);
        var dialog = new ContentDialog { XamlRoot = Controls.XamlRoot, Title = "Edit session times",
            Content = new ScrollViewer { Content = content, MaxHeight = 450 }, PrimaryButtonText = "Save", CloseButtonText = "Cancel" };
        DateTimeOffset LocalTime(CalendarDatePicker date, TimePicker time, DateTimeOffset original)
        {
            if (date.Date == null || time.SelectedTime == null) throw new InvalidOperationException("Enter both dates and times.");
            var value = DateTime.SpecifyKind(date.Date.Value.Date + time.Time, DateTimeKind.Unspecified);
            if (value == original.DateTime) return original;
            if (TimeZoneInfo.Local.IsInvalidTime(value) || TimeZoneInfo.Local.IsAmbiguousTime(value))
                throw new InvalidOperationException("This local time is missing or repeated due to a clock change. Choose an unambiguous time.");
            return new DateTimeOffset(value, TimeZoneInfo.Local.GetUtcOffset(value));
        }
        dialog.PrimaryButtonClick += (_, eventArgs) =>
        {
            try { tracker.UpdateTimes(sessionId, LocalTime(startDate, startTime, start), LocalTime(endDate, endTime, end)); ErrorText.Text = ""; Refresh(); }
            catch (Exception e) { eventArgs.Cancel = true; error.Text = e.Message; }
        };
        await dialog.ShowAsync();
    }
    private async void EditNotes(object sender, RoutedEventArgs args)
    {
        if (tracker == null || sender is not Button { Tag: Guid sessionId }) return;
        var session = tracker.State.Sessions.FirstOrDefault(s => s.SessionId == sessionId);
        if (session == null || session.EndTimeUtc == null) return;
        var editor = new TextBox
        {
            Header = "What did you work on?", Text = session.Notes,
            AcceptsReturn = true, TextWrapping = TextWrapping.Wrap, MinHeight = 120
        };
        var error = new TextBlock { TextWrapping = TextWrapping.Wrap, Foreground = new SolidColorBrush(Colors.Firebrick) };
        var content = new StackPanel { Spacing = 12 };
        content.Children.Add(new TextBlock { Text = $"{session.Project} — {session.StartTimeUtc.ToLocalTime():g}", TextWrapping = TextWrapping.Wrap });
        content.Children.Add(editor);
        content.Children.Add(error);
        var dialog = new ContentDialog
        {
            XamlRoot = Controls.XamlRoot, Title = "Edit session notes", Content = content,
            PrimaryButtonText = "Save", CloseButtonText = "Cancel"
        };
        dialog.PrimaryButtonClick += (_, eventArgs) =>
        {
            try { tracker.UpdateNotes(sessionId, editor.Text); ErrorText.Text = ""; Refresh(); }
            catch (Exception e) { eventArgs.Cancel = true; error.Text = "Could not save notes. " + e.Message; }
        };
        await dialog.ShowAsync();
    }
    private static string Elapsed(long seconds) => $"{seconds / 3600:00}:{seconds % 3600 / 60:00}:{seconds % 60:00}";
    private void UpdateClock()
    {
        var active = tracker?.State.Active;
        Status.Text = active == null ? "Ready when you are" : $"{active.Project}: {Elapsed(Math.Max(0, (long)(DateTimeOffset.UtcNow - active.StartTimeUtc).TotalSeconds))}";
    }
    private async void ChooseDataLocation(object sender, RoutedEventArgs args)
    {
        try
        {
            var picker = new FolderPicker();
            picker.FileTypeFilter.Add("*");
            WinRT.Interop.InitializeWithWindow.Initialize(picker, WinRT.Interop.WindowNative.GetWindowHandle(this));
            var folder = await picker.PickSingleFolderAsync();
            if (folder == null) return;
            if (string.IsNullOrEmpty(folder.Path)) throw new IOException("Choose a local or mounted cloud folder.");
            var firstRun = tracker == null;
            var next = location.Select(folder.Path, tracker?.State);
            tracker = next;
            Refresh();
            Nonprofits.SelectedItem = tracker.State.Nonprofits.FirstOrDefault(n => n.Id == tracker.State.Active?.ProjectId) ?? tracker.State.Nonprofits.FirstOrDefault();
            Notes.Text = tracker.State.Active?.Notes ?? "";
            ErrorText.Text = "";
            if (firstRun && tracker.State.Nonprofits.Length == 0)
            {
                SettingsPanel.Visibility = Visibility.Visible;
                NewName.Focus(FocusState.Programmatic);
            }
        }
        catch (Exception e) { ErrorText.Text = e.Message; }
    }
    private async void Export(object sender, RoutedEventArgs args)
    {
        try
        {
            var range = SelectedRange();
            var snapshot = tracker!.Csv(range);
            var picker = new FileSavePicker { SuggestedFileName = $"tick-{((ExportPeriod)ReportPeriod.SelectedIndex).ToString().ToLowerInvariant()}-{range.Start:yyyy-MM-dd}" };
            picker.FileTypeChoices.Add("CSV", new List<string> { ".csv" });
            WinRT.Interop.InitializeWithWindow.Initialize(picker, WinRT.Interop.WindowNative.GetWindowHandle(this));
            var file = await picker.PickSaveFileAsync();
            if (file != null) await Windows.Storage.FileIO.WriteTextAsync(file, snapshot);
            ErrorText.Text = "";
        }
        catch (Exception e) { ErrorText.Text = e.Message; }
    }
    private ExportRange SelectedRange() => ExportRange.For((ExportPeriod)ReportPeriod.SelectedIndex,
        DateOnly.FromDateTime((ReportDate.Date ?? DateTimeOffset.Now).DateTime));
    private void ReportChanged(object sender, SelectionChangedEventArgs args) => UpdateReport();
    private void NonprofitChanged(object sender, SelectionChangedEventArgs args)
    {
        if (Toggle != null) Toggle.IsEnabled = tracker?.State.Active != null || Nonprofits.SelectedItem != null;
    }
    private void ReportDateChanged(CalendarDatePicker sender, CalendarDatePickerDateChangedEventArgs args) => UpdateReport();
    private void UpdateReport()
    {
        if (ReportSummary == null || CopyButton == null || tracker == null) return;
        var range = SelectedRange();
        var count = tracker.ExportSessions(range).Length;
        ReportSummary.Text = $"{range.Start:yyyy-MM-dd} – {range.End.AddDays(-1):yyyy-MM-dd}: {count} completed sessions";
        ReportPreview.Text = count == 0 ? "No completed sessions in this period." : tracker.ClipboardText(range);
        ExportButton.IsEnabled = CopyButton.IsEnabled = count > 0;
        CopyStatus.Text = "";
    }
    private void CopyReport(object sender, RoutedEventArgs args)
    {
        try
        {
            var text = tracker!.ClipboardText(SelectedRange());
            if (text.Length == 0) return;
            var data = new Windows.ApplicationModel.DataTransfer.DataPackage();
            data.SetText(text);
            Windows.ApplicationModel.DataTransfer.Clipboard.SetContent(data);
            Windows.ApplicationModel.DataTransfer.Clipboard.Flush();
            CopyStatus.Text = "Copied durations and notes.";
            ErrorText.Text = "";
        }
        catch (Exception e) { ErrorText.Text = "Could not copy. " + e.Message; }
    }
    private void ShowSettings(object sender, RoutedEventArgs args) => SettingsPanel.Visibility =
        SettingsPanel.Visibility == Visibility.Visible ? Visibility.Collapsed : Visibility.Visible;
    private void WorkspaceResized(object sender, SizeChangedEventArgs args)
    {
        if (ReportPanel == null) return;
        var narrow = args.NewSize.Width < 760;
        Grid.SetColumn(ReportPanel, narrow ? 0 : 1);
        Grid.SetRow(ReportPanel, narrow ? 1 : 0);
        ReportColumn.Width = narrow ? new GridLength(0) : new GridLength(1, GridUnitType.Star);
    }
    private void CaptureResized(object sender, SizeChangedEventArgs args)
    {
        if (Toggle == null) return;
        var narrow = args.NewSize.Width < 500;
        Grid.SetColumn(Toggle, narrow ? 0 : 1);
        Grid.SetRow(Toggle, narrow ? 1 : 0);
        Grid.SetColumnSpan(Toggle, narrow ? 2 : 1);
    }
}
