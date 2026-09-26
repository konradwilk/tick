package org.nonprofithours

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
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val storage = StorageLocation(this)
        val loaded = runCatching { storage.open() }
        setContent { MaterialTheme {
            var tracker by remember { mutableStateOf(loaded.getOrNull()) }
            var storageError by remember { mutableStateOf(loaded.exceptionOrNull()?.message) }
            var location by remember { mutableStateOf(storage.label) }
            val chooseFolder = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocumentTree()) { uri ->
                if (uri != null) {
                    try {
                        val next = storage.select(uri, tracker)
                        tracker = next
                        location = storage.label
                        storageError = null
                    } catch (error: Exception) { storageError = error.message }
                }
            }
            Surface(Modifier.fillMaxSize()) {
                Column(Modifier.safeDrawingPadding()) {
                    storageError?.let { Text(it, Modifier.padding(20.dp), color = MaterialTheme.colorScheme.error) }
                    Box(Modifier.weight(1f)) {
                        val current = tracker
                        if (current != null) key(current) { TrackerScreen(current, location) { chooseFolder.launch(null) } }
                        else Column(Modifier.padding(20.dp)) {
                            Text("Choose a folder containing your data to resume. The original file was not changed.")
                            OutlinedButton(onClick = { chooseFolder.launch(null) }) { Text("Data location…") }
                        }
                    }
                }
            }
        } }
    }

    @Composable private fun TrackerScreen(tracker: Tracker, location: String, chooseFolder: () -> Unit) {
        var state by remember { mutableStateOf(tracker.state) }
        var selected by rememberSaveable { mutableStateOf(state.active?.nonprofitId ?: state.nonprofits.firstOrNull()?.id) }
        var notes by rememberSaveable { mutableStateOf(state.active?.notes.orEmpty()) }
        var name by rememberSaveable { mutableStateOf("") }
        var error by remember { mutableStateOf<String?>(null) }
        var now by remember { mutableStateOf(Instant.now()) }
        var exportSnapshot by rememberSaveable { mutableStateOf("") }
        var editingId by rememberSaveable { mutableStateOf<String?>(null) }
        var editedNotes by rememberSaveable { mutableStateOf("") }
        var editError by remember { mutableStateOf<String?>(null) }
        var reportPeriod by rememberSaveable { mutableStateOf("Monthly") }
        var reportDate by rememberSaveable { mutableStateOf(LocalDate.now().toString()) }
        var copyStatus by remember { mutableStateOf("") }
        var settings by remember { mutableStateOf(false) }
        val reportRange = runCatching { ExportRange.forDate(ExportPeriod.valueOf(reportPeriod), LocalDate.parse(reportDate)) }.getOrNull()
        val reportCount = reportRange?.let { tracker.exportSessions(it).size } ?: 0
        fun action(block: () -> Unit) {
            try { block(); state = tracker.state; error = null }
            catch (e: Exception) { error = e.message ?: "Unable to save hours." }
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
                OutlinedTextField(name, { name = it }, label = { Text("New nonprofit") }, enabled = active == null)
                Button(onClick = { action { selected = tracker.addNonprofit(name); name = "" } }, enabled = active == null && name.isNotBlank()) { Text("Add nonprofit") }
                OutlinedButton(onClick = chooseFolder) { Text("Data location…") }
                Text(location, style = MaterialTheme.typography.bodySmall)
                Text("All changes are saved here. Use one device at a time.", style = MaterialTheme.typography.bodySmall)
                Text("Timing continues when the app closes. Reopen and press Stop to finish.", style = MaterialTheme.typography.bodySmall)
                error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            } }, confirmButton = { TextButton(onClick = { settings = false }) { Text("Done") } }
        )
        editingId?.let { sessionId ->
            AlertDialog(
                onDismissRequest = { editingId = null },
                title = { Text("Edit session notes") },
                text = { Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    state.sessions.find { it.sessionId == sessionId }?.let {
                        Text("${it.nonprofitName} · ${it.startTimeUtc}")
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
        val history: @Composable () -> Unit = {
            HistoryPanel(state) { session -> editedNotes = session.notes; editError = null; editingId = session.sessionId }
        }
        val report: @Composable () -> Unit = {
            ReportPanel(reportPeriod, reportDate, reportRange, reportCount,
                reportRange?.let { tracker.clipboardText(it) }.orEmpty(), copyStatus,
                { reportPeriod = it; copyStatus = "" }, { reportDate = it; copyStatus = "" },
                onExport = { action { reportRange?.let { range ->
                    exportSnapshot = tracker.csv(range)
                    export.launch("nonprofit-hours-${reportPeriod.lowercase(java.util.Locale.ROOT)}-${range.start}.csv")
                } } },
                onCopy = { action { reportRange?.let { range ->
                    val clipboard = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                    clipboard.setPrimaryClip(ClipData.newPlainText("Task durations and notes", tracker.clipboardText(range)))
                    copyStatus = "Copied durations and notes."
                } } })
        }
        Column(Modifier.fillMaxSize().imePadding().padding(20.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Text("Nonprofit Hours", style = MaterialTheme.typography.titleLarge)
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
