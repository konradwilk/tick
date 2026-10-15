package org.timeisclearlykept

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.delay
import java.time.Instant
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context

class MainActivity : ComponentActivity() {
    private var focusGeneration by mutableStateOf(0)

    override fun onResume() {
        super.onResume()
        focusGeneration++
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (hasFocus) focusGeneration++
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val storage = StorageLocation(this)
        val loaded = runCatching { storage.open() }
        setContent { MaterialTheme {
            var tracker by remember { mutableStateOf(loaded.getOrNull()) }
            var storageError by remember { mutableStateOf(loaded.exceptionOrNull()?.message) }
            var location by remember { mutableStateOf(storage.label) }
            var openSettingsOnLoad by rememberSaveable { mutableStateOf(false) }
            val chooseFolder = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocumentTree()) { uri ->
                if (uri != null) {
                    try {
                        val next = storage.select(uri, tracker)
                        openSettingsOnLoad = tracker == null && next.state.nonprofits.isEmpty()
                        tracker = next
                        location = storage.label
                        storageError = null
                    } catch (error: Exception) { storageError = error.message }
                }
            }
            var promptedForFolder by rememberSaveable { mutableStateOf(false) }
            var explainingDataLocation by rememberSaveable { mutableStateOf(false) }
            LaunchedEffect(Unit) {
                if (!promptedForFolder && loaded.isSuccess && tracker == null) {
                    promptedForFolder = true
                    explainingDataLocation = true
                }
            }
            if (explainingDataLocation) {
                AlertDialog(
                    onDismissRequest = { explainingDataLocation = false },
                    title = { Text("Choose where to keep your data") },
                    text = { Text("Time is Clearkly Kept saves your projects and tracked hours in a JSON file named tick.json. Choose a folder where Time is Clearkly Kept can create this file, or select a folder containing your existing tick.json to continue using it. You can change the location later in Settings.") },
                    confirmButton = { TextButton(onClick = {
                        explainingDataLocation = false
                        chooseFolder.launch(null)
                    }) { Text("Choose data folder…") } },
                    dismissButton = { TextButton(onClick = { explainingDataLocation = false }) { Text("Later") } }
                )
            }
            Surface(Modifier.fillMaxSize()) {
                Column(Modifier.safeDrawingPadding()) {
                    storageError?.let { Text(it, Modifier.padding(20.dp), color = MaterialTheme.colorScheme.error) }
                    Box(Modifier.weight(1f)) {
                        val current = tracker
                        if (current != null) key(current) { TrackerScreen(current, location, openSettingsOnLoad, focusGeneration) { chooseFolder.launch(null) } }
                        else Column(Modifier.padding(20.dp)) {
                            Text("Time is Clearkly Kept saves your projects and tracked hours in a JSON file named tick.json. Choose a folder where Time is Clearkly Kept can create this file, or select a folder containing your existing tick.json to continue using it. You can change the location later in Settings.")
                            OutlinedButton(onClick = { chooseFolder.launch(null) }) { Text("Data location…") }
                        }
                    }
                }
            }
        } }
    }

    @Composable private fun TrackerScreen(tracker: Tracker, location: String, initialSettings: Boolean, focusGeneration: Int, chooseFolder: () -> Unit) {
        var state by remember { mutableStateOf(tracker.state) }
        val projectPreferences = remember { getSharedPreferences("hours-project", MODE_PRIVATE) }
        var selected by rememberSaveable {
            mutableStateOf(state.active?.projectId
                ?: state.nonprofits.find { it.id == projectPreferences.getString("lastSelectedProject", null) }?.id
                ?: state.nonprofits.firstOrNull()?.id)
        }
        LaunchedEffect(selected) {
            selected?.let { projectPreferences.edit().putString("lastSelectedProject", it).apply() }
        }
        var notes by rememberSaveable { mutableStateOf(state.active?.notes.orEmpty()) }
        var name by rememberSaveable { mutableStateOf("") }
        var error by remember { mutableStateOf<String?>(null) }
        LaunchedEffect(tracker, focusGeneration) {
            try {
                val previousActive = state.active
                tracker.reload()
                state = tracker.state
                selected = state.active?.projectId
                    ?: state.nonprofits.find { it.id == selected }?.id
                    ?: state.nonprofits.firstOrNull()?.id
                if (previousActive != state.active) notes = state.active?.notes.orEmpty()
            } catch (failure: Exception) { error = "Could not reload saved hours. " + failure.message }
        }
        var now by remember { mutableStateOf(Instant.now()) }
        var exportSnapshot by rememberSaveable { mutableStateOf("") }
        var editingId by rememberSaveable { mutableStateOf<String?>(null) }
        var editedNotes by rememberSaveable { mutableStateOf("") }
        var editError by remember { mutableStateOf<String?>(null) }
        var timeEditingId by rememberSaveable { mutableStateOf<String?>(null) }
        var editedStart by rememberSaveable { mutableStateOf("") }
        var editedEnd by rememberSaveable { mutableStateOf("") }
        var timeError by remember { mutableStateOf<String?>(null) }
        val timeFormat = DateTimeFormatter.ISO_LOCAL_DATE_TIME
        var reportPeriod by rememberSaveable { mutableStateOf("Monthly") }
        var reportDate by rememberSaveable { mutableStateOf(LocalDate.now().toString()) }
        var copyStatus by remember { mutableStateOf("") }
        var settings by rememberSaveable { mutableStateOf(initialSettings) }
        var manual by rememberSaveable { mutableStateOf(false) }
        var manualId by rememberSaveable {
            mutableStateOf(state.nonprofits.find {
                it.id == projectPreferences.getString("lastManualProject", null)
            }?.id)
        }
        fun selectManualProject(id: String) {
            manualId = id
            projectPreferences.edit().putString("lastManualProject", id).apply()
        }
        var manualNotes by rememberSaveable { mutableStateOf("") }
        val manualFormat = DateTimeFormatter.ofPattern("uuuu-MM-dd HH:mm").withResolverStyle(java.time.format.ResolverStyle.STRICT)
        var manualStart by rememberSaveable { mutableStateOf(LocalDateTime.now().minusHours(1).format(manualFormat)) }
        var manualEnd by rememberSaveable { mutableStateOf(LocalDateTime.parse(manualStart, manualFormat).plusMinutes(15).format(manualFormat)) }
        var manualEndEdited by rememberSaveable { mutableStateOf(false) }
        var manualConfirmation by remember { mutableStateOf<String?>(null) }
        var manualError by remember { mutableStateOf<String?>(null) }
        val reportRange = runCatching { ExportRange.forDate(ExportPeriod.valueOf(reportPeriod), LocalDate.parse(reportDate)) }.getOrNull()
        val reportCount = reportRange?.let { tracker.exportSessions(it).size } ?: 0
        fun action(block: () -> Unit) {
            try { block(); error = null }
            catch (e: Exception) { error = e.message ?: "Unable to save hours." }
            finally { state = tracker.state }
        }
        val export = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("text/csv")) { uri ->
            if (uri != null) action {
                val stream = requireNotNull(contentResolver.openOutputStream(uri, "wt")) { "Could not open export file." }
                stream.bufferedWriter(Charsets.UTF_8).use { it.write(exportSnapshot) }
            }
        }
        LaunchedEffect(state.active?.sessionId) {
            while (state.active != null) { now = Instant.now(); delay(1000) }
        }
        val active = state.active
        if (settings) AlertDialog(
            onDismissRequest = { settings = false }, title = { Text("Settings") },
            text = { Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                OutlinedTextField(name, { name = it }, label = { Text("New project") }, enabled = active == null)
                Button(onClick = { action { selected = tracker.addNonprofit(name); name = "" } }, enabled = active == null && name.isNotBlank()) { Text("Add nonprofit") }
                OutlinedButton(onClick = chooseFolder) { Text("Data location…") }
                OutlinedButton(onClick = { settings = false
                    manualId = state.nonprofits.find { it.id == projectPreferences.getString("lastManualProject", null) }?.id
                    manual = true; manualError = null; manualConfirmation = null }) { Text("Add session by hand…") }
                Text(location, style = MaterialTheme.typography.bodySmall)
                Text("All changes are saved here. Use one device at a time.", style = MaterialTheme.typography.bodySmall)
                Text("Timing continues when the app closes. Reopen and press Stop to finish.", style = MaterialTheme.typography.bodySmall)
                Text("This is version ${BuildConfig.VERSION_NAME}", style = MaterialTheme.typography.bodySmall)
                error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            } }, confirmButton = { TextButton(onClick = { settings = false }) { Text("Done") } }
        )
        fun localTime(value: String): Instant {
            val local = try { LocalDateTime.parse(value, manualFormat) }
                catch (_: Exception) { throw IllegalArgumentException("Enter dates and times as YYYY-MM-DD HH:mm.") }
            val offsets = ZoneId.systemDefault().rules.getValidOffsets(local)
            require(offsets.size == 1) { "This local time is missing or repeated due to a clock change. Choose an unambiguous time." }
            return local.toInstant(offsets.single())
        }
        val manualConflicts = runCatching { tracker.sessionConflicts(localTime(manualStart), localTime(manualEnd)) }.getOrDefault(emptyList())
        val manualSignature = "$manualId|$manualNotes|$manualStart|$manualEnd|" + manualConflicts.joinToString(";") { "${it.session.sessionId}|${it.session.startTimeUtc}|${it.session.endTimeUtc}" }
        if (manual) AlertDialog(
            onDismissRequest = { manual = false }, title = { Text("Add session by hand") },
            text = { Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Text("Project")
                state.nonprofits.forEach { nonprofit ->
                    Row {
                        RadioButton(selected = manualId == nonprofit.id, onClick = { manualConfirmation = null; selectManualProject(nonprofit.id) })
                        TextButton(onClick = { manualConfirmation = null; selectManualProject(nonprofit.id) }) { Text(nonprofit.name) }
                    }
                }
                if (state.nonprofits.isEmpty()) Text("Add a nonprofit in Settings first.")
                OutlinedTextField(manualNotes, { manualConfirmation = null; manualNotes = it }, label = { Text("What did you work on?") }, minLines = 2)
                Text("Local dates and times: YYYY-MM-DD HH:mm (24-hour)")
                OutlinedTextField(manualStart, {
                    manualConfirmation = null
                    manualStart = it
                    if (!manualEndEdited) runCatching { LocalDateTime.parse(it, manualFormat).plusMinutes(15).format(manualFormat) }
                        .onSuccess { suggested -> manualEnd = suggested }
                }, label = { Text("Started") }, singleLine = true)
                OutlinedTextField(manualEnd, { manualConfirmation = null; manualEnd = it; manualEndEdited = true }, label = { Text("Ended") }, singleLine = true)
                if (manualConflicts.isNotEmpty()) {
                    Text("Time overlap detected", color = MaterialTheme.colorScheme.error)
                    manualConflicts.forEach { Text(it.toString()) }
                }
                manualError?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            } },
            confirmButton = { TextButton(onClick = {
                try {
                    tracker.reload()
                    state = tracker.state
                    val latest = tracker.sessionConflicts(localTime(manualStart), localTime(manualEnd))
                    val signature = "$manualId|$manualNotes|$manualStart|$manualEnd|" + latest.joinToString(";") { "${it.session.sessionId}|${it.session.startTimeUtc}|${it.session.endTimeUtc}" }
                    if (latest.isNotEmpty() && manualConfirmation != signature) {
                        manualConfirmation = signature
                        manualError = "Review the conflicts. Choose Save anyway to confirm intentional overlap."
                        return@TextButton
                    }
                    tracker.addSession(requireNotNull(manualId) { "Select a project." }, manualNotes, localTime(manualStart), localTime(manualEnd))
                    state = tracker.state
                    manualNotes = ""
                    val savedEnd = LocalDateTime.parse(manualEnd, manualFormat)
                    manualStart = savedEnd.plusMinutes(1).format(manualFormat)
                    manualEnd = savedEnd.plusMinutes(15).format(manualFormat)
                    manualEndEdited = false
                    manualConfirmation = null
                    manualError = null
                    error = null
                    copyStatus = ""
                } catch (e: Exception) { manualError = e.message ?: "Could not save session." }
            }) { Text(if (manualConflicts.isNotEmpty() && manualConfirmation == manualSignature) "Save anyway" else "Save") } },
            dismissButton = { TextButton(onClick = { manual = false }) { Text("Cancel") } }
        )
        editingId?.let { sessionId ->
            AlertDialog(
                onDismissRequest = { editingId = null },
                title = { Text("Edit session notes") },
                text = { Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    state.sessions.find { it.sessionId == sessionId }?.let {
                        Text("${it.project} · ${it.startTimeUtc}")
                    }
                    OutlinedTextField(editedNotes, { editedNotes = it }, Modifier.fillMaxWidth(),
                        label = { Text("What did you work on?") }, minLines = 3, maxLines = 8)
                    editError?.let { Text(it, color = MaterialTheme.colorScheme.error) }
                } },
                confirmButton = { TextButton(onClick = {
                    try {
                        tracker.updateNotes(sessionId, editedNotes)
                        state = tracker.state
                        editingId = null
                        error = null
                    } catch (e: Exception) { editError = e.message ?: "Could not save notes." }
                }) { Text("Save") } },
                dismissButton = { TextButton(onClick = { editingId = null }) { Text("Cancel") } }
            )
        }
        timeEditingId?.let { sessionId ->
            AlertDialog(onDismissRequest = { timeEditingId = null }, title = { Text("Edit session times") },
                text = { Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text(state.sessions.find { it.sessionId == sessionId }?.project.orEmpty())
                    Text("Local dates and times: YYYY-MM-DDTHH:mm:ss (24-hour). Fractional seconds are optional.")
                    OutlinedTextField(editedStart, { editedStart = it }, label = { Text("Started") }, singleLine = true)
                    OutlinedTextField(editedEnd, { editedEnd = it }, label = { Text("Ended") }, singleLine = true)
                    timeError?.let { Text(it, color = MaterialTheme.colorScheme.error) }
                } },
                confirmButton = { TextButton(onClick = {
                    try {
                        val original = requireNotNull(state.sessions.find { it.sessionId == sessionId }) { "The session could not be found." }
                        fun localTime(text: String, saved: String): Instant {
                            val instant = Instant.parse(saved)
                            if (text == instant.atZone(ZoneId.systemDefault()).format(timeFormat)) return instant
                            val local = try { LocalDateTime.parse(text, timeFormat) }
                                catch (_: Exception) { throw IllegalArgumentException("Enter dates and times as YYYY-MM-DDTHH:mm:ss.") }
                            val offsets = ZoneId.systemDefault().rules.getValidOffsets(local)
                            require(offsets.size == 1) { "This local time is missing or repeated due to a clock change. Choose an unambiguous time." }
                            return local.toInstant(offsets.single())
                        }
                        tracker.updateTimes(sessionId, localTime(editedStart, original.startTimeUtc), localTime(editedEnd, requireNotNull(original.endTimeUtc)))
                        state = tracker.state
                        timeEditingId = null
                        copyStatus = ""
                        error = null
                    } catch (e: Exception) { timeError = e.message ?: "Could not save times." }
                }) { Text("Save") } },
                dismissButton = { TextButton(onClick = { timeEditingId = null }) { Text("Cancel") } })
        }
        val history: @Composable () -> Unit = {
            HistoryPanel(state, onDelete = { session -> action { tracker.deleteSession(session.sessionId); copyStatus = "" } }, onEditTimes = { session ->
                editedStart = Instant.parse(session.startTimeUtc).atZone(ZoneId.systemDefault()).format(timeFormat)
                editedEnd = Instant.parse(session.endTimeUtc).atZone(ZoneId.systemDefault()).format(timeFormat)
                timeError = null
                timeEditingId = session.sessionId
            }) { session -> editedNotes = session.notes; editError = null; editingId = session.sessionId }
        }
        val report: @Composable () -> Unit = {
            ReportPanel(reportPeriod, reportDate, reportRange, reportCount,
                reportRange?.let { tracker.clipboardText(it) }.orEmpty(), copyStatus,
                { reportPeriod = it; copyStatus = "" }, { reportDate = it; copyStatus = "" },
                onExport = { action { reportRange?.let { range ->
                    exportSnapshot = tracker.csv(range)
                    export.launch("tick-${reportPeriod.lowercase(java.util.Locale.ROOT)}-${range.start}.csv")
                } } },
                onCopy = { action { reportRange?.let { range ->
                    val clipboard = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                    clipboard.setPrimaryClip(ClipData.newPlainText("Task durations and notes", tracker.clipboardText(range)))
                    copyStatus = "Copied durations and notes."
                } } })
        }
        Column(Modifier.fillMaxSize().imePadding().padding(20.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Text("Time is Clearly Kept", style = MaterialTheme.typography.titleLarge)
                TextButton(onClick = { settings = true }) { Text("Settings") }
            }
            CapturePanel(state, selected, notes, now, { selected = it }, { notes = it },
                onToggle = { action { if (active != null) { tracker.stop(); notes = "" } else selected?.let { tracker.start(it, notes) } } },
                onSettings = { settings = true })
            error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            HorizontalDivider()
            BoxWithConstraints(Modifier.weight(1f)) {
                if (maxWidth >= 800.dp) {
                    Row(horizontalArrangement = Arrangement.spacedBy(24.dp)) {
                        Column(Modifier.weight(1f).verticalScroll(rememberScrollState())) { history() }
                        Column(Modifier.weight(1f).verticalScroll(rememberScrollState())) { report() }
                    }
                } else {
                    Column(Modifier.fillMaxWidth().verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(24.dp)) {
                        history()
                        report()
                    }
                }
            }
        }
    }
}
