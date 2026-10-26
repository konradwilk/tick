using HoursCore;
using Microsoft.UI;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Windows.Storage.Pickers;
namespace Tick;
public sealed partial class MainWindow : Window
{
    private readonly Dictionary<DateOnly, HistoryWeekEntries> historyWeeks = new();
    private readonly DateOnly historyCutoff = DateOnly.FromDateTime(DateTime.Today.AddMonths(-1));
    private Tracker? tracker;
    private bool refreshingProjects;
    private bool writing;
    private async Task WriteAsync(Button? button, Func<Task> action, ContentDialog? dialog = null, bool allowCancel = false)
    {
        if (writing) return;
        writing = true;
        var root = (FrameworkElement)Content;
        var rootHitTest = root.IsHitTestVisible;
        var dialogHitTest = dialog?.IsHitTestVisible ?? true;
        var background = button?.Background;
        var foreground = button?.Foreground;
        var label = button?.Content;
        var contentBinding = button?.GetBindingExpression(Button.ContentProperty)?.ParentBinding;
        var primary = button?.Name == "PrimaryButton";
        var dialogLabel = dialog == null ? null : primary ? dialog.PrimaryButtonText : dialog.SecondaryButtonText;
        var enabled = button?.IsEnabled ?? true;
        var helpText = button == null ? "" : Microsoft.UI.Xaml.Automation.AutomationProperties.GetHelpText(button);
        var started = System.Diagnostics.Stopwatch.StartNew();
        void BlockKeys(object sender, Microsoft.UI.Xaml.Input.KeyRoutedEventArgs args) => args.Handled = true;
        var keys = new[] { "ButtonBackground", "ButtonBackgroundPointerOver", "ButtonBackgroundPressed", "ButtonBackgroundDisabled", "ButtonForegroundDisabled" };
        var previous = keys.Select(key => button?.Resources.ContainsKey(key) == true ? button.Resources[key] : null).ToArray();
        try
        {
            root.IsHitTestVisible = false;
            root.PreviewKeyDown += BlockKeys;
            if (dialog != null && !allowCancel) { dialog.IsHitTestVisible = false; dialog.PreviewKeyDown += BlockKeys; }
            if (button != null)
            {
                var busy = new SolidColorBrush(Colors.DarkGoldenrod);
                button.Background = busy;
                button.Foreground = new SolidColorBrush(Colors.White);
                if (dialog == null) button.Content = "Working…";
                else if (primary) dialog.PrimaryButtonText = "Working…";
                else dialog.SecondaryButtonText = "Working…";
                foreach (var key in keys) button.Resources[key] = key == "ButtonForegroundDisabled" ? new SolidColorBrush(Colors.White) : busy;
                button.IsEnabled = false;
                Microsoft.UI.Xaml.Automation.AutomationProperties.SetHelpText(button, "Working. Please wait.");
            }
            // Let Windows render the feedback before starting a write.
            await Task.Delay(75);
            await action();
        }
        finally
        {
            var remaining = 250 - (int)started.ElapsedMilliseconds;
            if (remaining > 0) await Task.Delay(remaining);
            if (button != null)
            {
                button.Background = background;
                button.Foreground = foreground;
                if (dialog != null)
                {
                    // Keep the dialog's binding intact and preserve labels changed by the action,
                    // such as "Save anyway" or "Connect".
                    if (primary && dialog.PrimaryButtonText == "Working…") dialog.PrimaryButtonText = dialogLabel;
                    else if (!primary && dialog.SecondaryButtonText == "Working…") dialog.SecondaryButtonText = dialogLabel;
                }
                else if (contentBinding != null) button.SetBinding(Button.ContentProperty, contentBinding);
                else button.Content = label;
                button.IsEnabled = enabled;
                for (var i = 0; i < keys.Length; i++)
                    if (previous[i] is object value) button.Resources[keys[i]] = value;
                    else button.Resources.Remove(keys[i]);
                Microsoft.UI.Xaml.Automation.AutomationProperties.SetHelpText(button, helpText);
            }
            root.IsHitTestVisible = rootHitTest;
            root.PreviewKeyDown -= BlockKeys;
            if (dialog != null) dialog.IsHitTestVisible = dialogHitTest;
            if (dialog != null) dialog.PreviewKeyDown -= BlockKeys;
            writing = false;
        }
    }
    private static Button? DialogButton(DependencyObject parent, string name)
    {
        for (var i = 0; i < VisualTreeHelper.GetChildrenCount(parent); i++)
        {
            var child = VisualTreeHelper.GetChild(parent, i);
            if (child is Button button && button.Name == name) return button;
            if (DialogButton(child, name) is Button found) return found;
        }
        return null;
    }
    private void HandleDialogWrite(ContentDialog dialog, Func<ContentDialogButtonClickEventArgs, Task> action, Func<bool>? allowCancel = null)
    {
        dialog.PrimaryButtonClick += async (_, args) =>
        {
            if (writing) { args.Cancel = true; return; }
            var deferral = args.GetDeferral();
            try { await WriteAsync(DialogButton(dialog, "PrimaryButton"), () => action(args), dialog, allowCancel?.Invoke() == true); }
            catch (Exception e) { args.Cancel = true; ErrorText.Text = e.Message; }
            finally { deferral.Complete(); }
        };
    }
    private readonly string projectSettingsPath = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "TimeIsClearlyKept", "last-project");
    private Nonprofit? DefaultProject()
    {
        Guid.TryParse(ReadLastProject(), out var saved);
        return tracker!.State.Nonprofits.FirstOrDefault(n => n.Id == tracker.State.Active?.ProjectId)
            ?? tracker.State.Nonprofits.FirstOrDefault(n => n.Id == saved)
            ?? tracker.State.Nonprofits.FirstOrDefault();
    }
    private string? ReadLastProject()
    {
        try { return File.Exists(projectSettingsPath) ? File.ReadAllText(projectSettingsPath) : null; }
        catch (Exception) { return null; }
    }
    private readonly StorageLocation location = new(
        Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "TimeIsClearlyKept", "location.json"),
        Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "TimeIsClearlyKept", "tick.json"));
    private readonly DispatcherTimer timer = new() { Interval = TimeSpan.FromSeconds(1) };
    public MainWindow()
    {
        InitializeComponent();
        RefreshStorageChoices();
        VersionText.Text = "This is version " + BuildVersion.Current;
        AppWindow.Resize(new Windows.Graphics.SizeInt32(1100, 800));
        ReportDate.Date = DateTimeOffset.Now;
        timer.Tick += (_, _) => UpdateClock();
        timer.Start();
        Closed += (_, _) => timer.Stop();
        Activated += (_, args) =>
        {
            if (args.WindowActivationState != WindowActivationState.Deactivated) Reload();
        };
        try
        {
            tracker = location.Open();
            Refresh();
            Nonprofits.SelectedItem = DefaultProject();
            Notes.Text = tracker.State.Active?.Notes ?? "";

        }
        catch (Exception e)
        {
            Nonprofits.IsEnabled = Notes.IsEnabled = NewName.IsEnabled = AddButton.IsEnabled =
                Toggle.IsEnabled = ExportButton.IsEnabled = CopyButton.IsEnabled = false;
            if (e is FileNotFoundException or DirectoryNotFoundException)
            {
                ErrorText.Text = "Choose Local file or Google Sheets (Settings → Data storage).";
                ((FrameworkElement)Content).Loaded += PromptForDataLocation;
            }
            else ErrorText.Text = "Could not load saved hours. Your file was not changed. " + e.Message;
        }
    }
    private void Reload()
    {
        if (tracker == null || writing) return;
        try
        {
            var previousActive = tracker.State.Active;
            var selected = (Nonprofits.SelectedItem as Nonprofit)?.Id;
            tracker.Reload();
            Refresh();
            Nonprofits.SelectedItem = tracker.State.Active != null
                ? DefaultProject()
                : tracker.State.Nonprofits.FirstOrDefault(n => n.Id == selected) ?? DefaultProject();
            if (previousActive != tracker.State.Active) Notes.Text = tracker.State.Active?.Notes ?? "";
        }
        catch (Exception e) { ErrorText.Text = "Could not reload saved hours. " + e.Message; }
    }
    private async void PromptForDataLocation(object sender, RoutedEventArgs args)
    {
        ((FrameworkElement)Content).Loaded -= PromptForDataLocation;
        var dialog = new ContentDialog
        {
            XamlRoot = Controls.XamlRoot,
            Title = "Choose where to keep your data",
            Content = new TextBlock { Text = "Choose Local file (tick.json) for offline storage in a folder, or Google Sheets to share data across devices over the internet. You can switch in Settings. An empty destination receives your current data; an existing destination is opened without merging.", TextWrapping = TextWrapping.Wrap },
            PrimaryButtonText = "Local file (tick.json)…",
            SecondaryButtonText = "Google Sheets…",
            CloseButtonText = "Later",
            DefaultButton = ContentDialogButton.Primary
        };
        var result = await dialog.ShowAsync();
        if (result == ContentDialogResult.Primary) ChooseDataLocation(sender, args);
        else if (result == ContentDialogResult.Secondary) ChooseSheets(sender, args);
    }
    private async void ChooseSheets(object sender, RoutedEventArgs args)
    {
        var account = new GoogleAccount(); var api = new GoogleSheetsAPI(account);
        using var cancel = new CancellationTokenSource();
        var choices = new ComboBox { Header = "Spreadsheet", Visibility = Visibility.Collapsed };
        choices.Items.Add(new GoogleSpreadsheet("", "Create a new spreadsheet")); choices.SelectedIndex = 0;
        var name = new TextBox { Text = "Time is Clearly Kept", Header = "Spreadsheet name", Visibility = Visibility.Collapsed };
        choices.SelectionChanged += (_, _) => name.Visibility = choices.SelectedIndex == 0 ? Visibility.Visible : Visibility.Collapsed;
        var error = new TextBlock { TextWrapping = TextWrapping.Wrap };
        var panel = new StackPanel { Spacing = 12 };
        panel.Children.Add(new TextBlock { Text = "Sign in, then create a spreadsheet or open one Tick can access. New spreadsheets receive your current data. Existing Tick data opens without merging. Use one device at a time.", TextWrapping = TextWrapping.Wrap });
        panel.Children.Add(choices); panel.Children.Add(name); panel.Children.Add(error);
        var dialog = new ContentDialog { XamlRoot = Controls.XamlRoot, Title = "Google Sheets", Content = panel, PrimaryButtonText = "Sign in with Google", CloseButtonText = "Cancel" };
        Tracker? next = null; bool signedIn = false;
        dialog.CloseButtonClick += (_, _) => cancel.Cancel();
        HandleDialogWrite(dialog, async eventArgs => {
            try {
                error.Text = "Connecting to Google…";
                if (!signedIn) {
                    await account.SignInAsync(cancel.Token);
                    var files = await Task.Run(api.List, cancel.Token);
                    foreach (var file in files) choices.Items.Add(file);
                    signedIn = true; choices.Visibility = name.Visibility = Visibility.Visible;
                    dialog.PrimaryButtonText = "Connect"; dialog.SecondaryButtonText = "Sign out";
                    eventArgs.Cancel = true;
                } else {
                    var file = (GoogleSpreadsheet)choices.SelectedItem; var title = name.Text; var state = tracker?.State;
                    next = await Task.Run(() => {
                        var store = file.Id.Length == 0 ? api.Create(title) : new SheetsStore(new SheetsConfiguration(file.Id,file.Name),api);
                        return location.SelectSheets(store,state);
                    },cancel.Token);
                }
                error.Text = "";
            } catch (Exception problem) { eventArgs.Cancel = true; error.Text = problem.Message; }
        }, () => !signedIn);
        dialog.SecondaryButtonClick += async (_, eventArgs) => {
            eventArgs.Cancel = true;
            if (writing) return;
            var deferral = eventArgs.GetDeferral();
            try { await WriteAsync(DialogButton(dialog, "SecondaryButton"), () => Task.Run(account.SignOut), dialog); signedIn = false; choices.Items.Clear(); choices.Items.Add(new GoogleSpreadsheet("","Create a new spreadsheet")); choices.SelectedIndex=0;
                choices.Visibility = name.Visibility = Visibility.Collapsed; dialog.PrimaryButtonText="Sign in with Google"; dialog.SecondaryButtonText=""; }
            catch (Exception problem) { error.Text=problem.Message; }
            finally { deferral.Complete(); }
        };
        await dialog.ShowAsync(); cancel.Cancel();
        if (next == null) return;
        tracker = next; Refresh(); Nonprofits.SelectedItem = DefaultProject();
        Notes.Text = tracker.State.Active?.Notes ?? ""; ErrorText.Text = "";
        SettingsPanel.Visibility = Visibility.Visible;
    }
    private async void Perform(object sender, Func<Task> action)
    {
        if (writing) return;
        try { await WriteAsync(sender as Button, action); ErrorText.Text = ""; Refresh(); }
        catch (Exception e) { if (tracker != null) Refresh(); ErrorText.Text = e.Message; }
    }
    private void AddNonprofit(object sender, RoutedEventArgs args) => Perform(sender, async () =>
    {
        var name = NewName.Text;
        var id = await Task.Run(() => tracker!.AddNonprofit(name));
        NewName.Text = "";
        Refresh();
        Nonprofits.SelectedItem = tracker!.State.Nonprofits.First(n => n.Id == id);
    });
    private void ToggleTracking(object sender, RoutedEventArgs args) => Perform(sender, async () =>
    {
        if (tracker!.State.Active != null) { await Task.Run(() => tracker.Stop()); Notes.Text = ""; }
        else if (Nonprofits.SelectedItem is Nonprofit nonprofit) { var notes = Notes.Text; await Task.Run(() => tracker.Start(nonprofit.Id, notes)); }
        else throw new InvalidOperationException("Select a project first.");
    });
    private void RefreshStorageChoices()
    {
        void Update(Button button, string title, bool active)
        {
            button.Content = title + (active ? " — ✓ Active" : " — Not active");
            button.Background = new SolidColorBrush(active
                ? Windows.UI.Color.FromArgb(36, 46, 160, 67)
                : Windows.UI.Color.FromArgb(18, 128, 128, 128));
            button.BorderBrush = new SolidColorBrush(active
                ? Windows.UI.Color.FromArgb(255, 46, 160, 67)
                : Windows.UI.Color.FromArgb(100, 128, 128, 128));
            button.BorderThickness = new Thickness(active ? 2 : 1);
            Microsoft.UI.Xaml.Automation.AutomationProperties.SetHelpText(button, active ? "Active storage" : "Not active");
        }
        Update(LocalStorageButton, "Local file (tick.json)…", tracker != null && !location.UsesGoogleSheets);
        Update(SheetsStorageButton, "Google Sheets…", tracker != null && location.UsesGoogleSheets);
    }

    private void Refresh()
    {
        Toggle.IsEnabled = true;
        DataLocation.Text = location.Label;
        RefreshStorageChoices();
        var state = tracker!.State;
        FirstRun.Visibility = state.Nonprofits.Length == 0 ? Visibility.Visible : Visibility.Collapsed;
        EmptyHistory.Visibility = state.Sessions.Length == 0 ? Visibility.Visible : Visibility.Collapsed;
        var selected = (Nonprofits.SelectedItem as Nonprofit)?.Id;
        refreshingProjects = true;
        Nonprofits.ItemsSource = state.Nonprofits;
        Nonprofits.SelectedItem = state.Nonprofits.FirstOrDefault(n => n.Id == selected);
        refreshingProjects = false;
        var active = state.Active != null;
        Nonprofits.IsEnabled = Notes.IsEnabled = NewName.IsEnabled = AddButton.IsEnabled = !active;
        Toggle.Content = active ? "Stop" : "Start";
        Toggle.Background = new SolidColorBrush(active ? Colors.Firebrick : Colors.ForestGreen);
        Total.Text = $"Completed: {state.Sessions.Sum(s => s.DurationSeconds ?? 0) / 3600.0:F2} hours";
        UpdateReport();
        History.ItemsSource = state.Sessions.OrderByDescending(s => s.StartTimeUtc)
            .GroupBy(s => ExportRange.For(ExportPeriod.Weekly, DateOnly.FromDateTime(s.StartTimeUtc.LocalDateTime)).Start)
            .Select(group => {
                var lastDay = group.Key.AddDays(6);
                var firstLabel = group.Key.Year == lastDay.Year ? group.Key.ToString("MMM d") : group.Key.ToString("MMM d, yyyy");
                var entries = group.Select(s => new HistoryEntry(s.SessionId,
                    $"{s.Project} — {s.StartTimeUtc.ToLocalTime():g}\n{(s.DurationSeconds is long seconds ? Elapsed(seconds) : "In progress")}\n{s.Notes}", s.EndTimeUtc != null,
                    s.EndTimeUtc != null && s.DurationSeconds is >= 0 and < 60 ? Visibility.Visible : Visibility.Collapsed)).ToArray();
                if (!historyWeeks.TryGetValue(group.Key, out var week))
                {
                    week = new HistoryWeekEntries($"{firstLabel} – {lastDay:MMM d, yyyy}", entries,
                        group.Any(s => DateOnly.FromDateTime(s.StartTimeUtc.LocalDateTime) >= historyCutoff));
                    historyWeeks[group.Key] = week;
                }
                week.Entries = entries;
                return week;
            }).ToArray();
        UpdateClock();
    }
    public record HistoryEntry(Guid SessionId, string Summary, bool CanEdit, Visibility DeleteVisibility);
    public class HistoryWeekEntries(string weekLabel, HistoryEntry[] entries, bool isExpanded)
    {
        public string WeekLabel { get; } = weekLabel;
        public HistoryEntry[] Entries { get; set; } = entries;
        public bool IsExpanded { get; set; } = isExpanded;
    }
    private void DeleteSession(object sender, RoutedEventArgs args)
    {
        if (tracker != null && sender is Button { Tag: Guid id }) Perform(sender, () => Task.Run(() => tracker.DeleteSession(id)));
    }
    private async void AddManualSession(object sender, RoutedEventArgs args)
    {
        if (tracker == null) return;
        var manualSettingsPath = Path.Combine(Path.GetDirectoryName(projectSettingsPath)!, "last-manual-project");
        string? savedManualProject = null;
        try { if (File.Exists(manualSettingsPath)) savedManualProject = File.ReadAllText(manualSettingsPath); }
        catch (Exception) { }
        Guid.TryParse(savedManualProject, out var manualProjectId);
        var nonprofit = new ComboBox { Header = "Project", DisplayMemberPath = "Name", ItemsSource = tracker.State.Nonprofits,
            SelectedItem = tracker.State.Nonprofits.FirstOrDefault(n => n.Id == manualProjectId)
                ?? Nonprofits.SelectedItem ?? tracker.State.Nonprofits.FirstOrDefault(), HorizontalAlignment = HorizontalAlignment.Stretch };
        void RememberManualProject()
        {
            if (nonprofit.SelectedItem is not Nonprofit project) return;
            try
            {
                Directory.CreateDirectory(Path.GetDirectoryName(manualSettingsPath)!);
                File.WriteAllText(manualSettingsPath, project.Id.ToString());
            }
            catch (Exception e) { ErrorText.Text = "Could not remember the manual project: " + e.Message; }
        }
        nonprofit.SelectionChanged += (_, _) => RememberManualProject();
        RememberManualProject();
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
        static DateTimeOffset LocalTime(CalendarDatePicker date, TimePicker time)
        {
            if (date.Date == null || time.SelectedTime == null) throw new InvalidOperationException("Enter both dates and times.");
            var value = DateTime.SpecifyKind(date.Date.Value.Date + time.Time, DateTimeKind.Unspecified);
            if (TimeZoneInfo.Local.IsInvalidTime(value)) throw new InvalidOperationException("This local time does not exist due to a clock change.");
            if (TimeZoneInfo.Local.IsAmbiguousTime(value)) throw new InvalidOperationException("This local time occurs twice due to a clock change. Choose an unambiguous time.");
            return new DateTimeOffset(value, TimeZoneInfo.Local.GetUtcOffset(value));
        }
        var warning = new TextBlock { TextWrapping = TextWrapping.Wrap };
        content.Children.Add(warning);
        string? confirmation = null;
        SessionConflict[] Conflicts() => tracker.SessionConflicts(LocalTime(startDate, startTime), LocalTime(endDate, endTime));
        void UpdateConflicts()
        {
            confirmation = null;
            dialog.PrimaryButtonText = "Save";
            try {
                var conflicts = Conflicts();
                warning.Text = conflicts.Length == 0 ? "" : "Time overlap detected\n\n" + string.Join("\n\n", conflicts.Select(c => c.ToString()));
            } catch (Exception) { warning.Text = ""; }
        }
        startDate.DateChanged += (_, _) => UpdateConflicts();
        startTime.TimeChanged += (_, _) => UpdateConflicts();
        endDate.DateChanged += (_, _) => UpdateConflicts();
        endTime.TimeChanged += (_, _) => UpdateConflicts();
        activity.TextChanged += (_, _) => UpdateConflicts();
        nonprofit.SelectionChanged += (_, _) => UpdateConflicts();
        UpdateConflicts();
        HandleDialogWrite(dialog, async eventArgs =>
        {
            try
            {
                if (nonprofit.SelectedItem is not Nonprofit selected) throw new InvalidOperationException("Select a project. Add one in Settings first if needed.");
                await Task.Run(() => tracker.Reload());
                Refresh();
                var conflicts = Conflicts();
                var signature = $"{selected.Id}|{activity.Text}|{LocalTime(startDate, startTime):O}|{LocalTime(endDate, endTime):O}|" + string.Join(";", conflicts.Select(c => $"{c.Session.SessionId}|{c.Session.StartTimeUtc:O}|{c.Session.EndTimeUtc:O}"));
                warning.Text = conflicts.Length == 0 ? "" : "Time overlap detected\n\n" + string.Join("\n\n", conflicts.Select(c => c.ToString()));
                if (conflicts.Length > 0 && confirmation != signature) {
                    confirmation = signature;
                    eventArgs.Cancel = true;
                    dialog.PrimaryButtonText = "Save anyway";
                    error.Text = "Review the conflicts. Choose Save anyway to confirm intentional overlap.";
                    return;
                }
                var notes = activity.Text;
                var from = LocalTime(startDate, startTime);
                var to = LocalTime(endDate, endTime);
                await Task.Run(() => tracker.AddSession(selected.Id, notes, from, to));
                var savedEnd = endDate.Date!.Value.Date + endTime.Time;
                var nextStart = savedEnd.AddMinutes(1);
                var nextEnd = savedEnd.AddMinutes(15);
                endEdited = true;
                updatingEnd = true;
                startDate.Date = nextStart;
                startTime.Time = nextStart.TimeOfDay;
                endDate.Date = nextEnd;
                endTime.Time = nextEnd.TimeOfDay;
                updatingEnd = false;
                endEdited = false;
                activity.Text = "";
                confirmation = null;
                dialog.PrimaryButtonText = "Save";
                error.Text = "Session saved.";
                eventArgs.Cancel = true;
                ErrorText.Text = "";
                Refresh();
            }
            catch (Exception e) { eventArgs.Cancel = true; error.Text = e.Message; }
        });
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
        HandleDialogWrite(dialog, async eventArgs =>
        {
            try { var from = LocalTime(startDate, startTime, start); var to = LocalTime(endDate, endTime, end); await Task.Run(() => tracker.UpdateTimes(sessionId, from, to)); ErrorText.Text = ""; Refresh(); }
            catch (Exception e) { eventArgs.Cancel = true; error.Text = e.Message; }
        });
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
        HandleDialogWrite(dialog, async eventArgs =>
        {
            try { var notes = editor.Text; await Task.Run(() => tracker.UpdateNotes(sessionId, notes)); ErrorText.Text = ""; Refresh(); }
            catch (Exception e) { eventArgs.Cancel = true; error.Text = "Could not save notes. " + e.Message; }
        });
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
            var state = tracker?.State;
            await WriteAsync(LocalStorageButton, async () => tracker = await Task.Run(() => location.Select(folder.Path, state)));
            Refresh();
            Nonprofits.SelectedItem = DefaultProject();
            Notes.Text = tracker!.State.Active?.Notes ?? "";
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
            if (file != null) await WriteAsync(ExportButton, async () => await Windows.Storage.FileIO.WriteTextAsync(file, snapshot));
            ErrorText.Text = "";
        }
        catch (Exception e) { ErrorText.Text = e.Message; }
    }
    private ExportRange SelectedRange() => ExportRange.For((ExportPeriod)ReportPeriod.SelectedIndex,
        DateOnly.FromDateTime((ReportDate.Date ?? DateTimeOffset.Now).DateTime));
    private void ReportChanged(object sender, SelectionChangedEventArgs args) => UpdateReport();
    private void NonprofitChanged(object sender, SelectionChangedEventArgs args)
    {
        if (!refreshingProjects && Nonprofits.SelectedItem is Nonprofit project)
        {
            try
            {
                Directory.CreateDirectory(Path.GetDirectoryName(projectSettingsPath)!);
                File.WriteAllText(projectSettingsPath, project.Id.ToString());
            }
            catch (Exception e) { ErrorText.Text = "Could not remember the project: " + e.Message; }
        }
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
    private async void CopyReport(object sender, RoutedEventArgs args)
    {
        try
        {
            var text = tracker!.ClipboardText(SelectedRange());
            if (text.Length == 0) return;
            await WriteAsync(CopyButton, () => {
                var data = new Windows.ApplicationModel.DataTransfer.DataPackage();
                data.SetText(text);
                Windows.ApplicationModel.DataTransfer.Clipboard.SetContent(data);
                Windows.ApplicationModel.DataTransfer.Clipboard.Flush();
                return Task.CompletedTask;
            });
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
