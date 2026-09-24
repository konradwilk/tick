package org.nonprofithours

import android.os.Bundle
import android.util.AtomicFile
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.delay
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import java.io.File
import java.time.Instant
import java.time.Duration

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val loaded = runCatching {
            val file = AtomicFile(File(filesDir, "sessions.json"))
            // openRead also recovers an interrupted write's backup, if present.
            val initial = if (file.baseFile.exists() || File(file.baseFile.path + ".bak").exists())
                Json.decodeFromString<TrackerState>(file.openRead().bufferedReader().use { it.readText() }) else TrackerState()
            Tracker(initial) { next ->
                val bytes = Json.encodeToString(next).toByteArray(Charsets.UTF_8)
                val stream = file.startWrite()
                try { stream.write(bytes); file.finishWrite(stream) }
                catch (e: Exception) { file.failWrite(stream); throw e }
            }
        }
        setContent { MaterialTheme {
            Surface(Modifier.fillMaxSize()) {
                val tracker = loaded.getOrNull()
                if (tracker == null) Text("Could not load saved hours. Your file was not changed. ${loaded.exceptionOrNull()?.message}", Modifier.padding(24.dp))
                else TrackerScreen(tracker)
            }
        } }
    }

    @Composable private fun TrackerScreen(tracker: Tracker) {
        var state by remember { mutableStateOf(tracker.state) }
        var selected by rememberSaveable { mutableStateOf(state.active?.nonprofitId ?: state.nonprofits.firstOrNull()?.id) }
        var notes by rememberSaveable { mutableStateOf(state.active?.notes.orEmpty()) }
        var name by rememberSaveable { mutableStateOf("") }
        var error by remember { mutableStateOf<String?>(null) }
        var menu by remember { mutableStateOf(false) }
        var now by remember { mutableStateOf(Instant.now()) }
        var exportSnapshot by rememberSaveable { mutableStateOf("") }
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
        LazyColumn(Modifier.fillMaxSize().safeDrawingPadding().imePadding().padding(20.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            item { Text("Nonprofit Hours", style = MaterialTheme.typography.headlineLarge) }
            item { Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(name, { name = it }, Modifier.weight(1f), label = { Text("New nonprofit") }, enabled = active == null)
                Button(onClick = { action { selected = tracker.addNonprofit(name); name = "" } }, enabled = active == null && name.isNotBlank()) { Text("Add") }
            } }
            item { Box {
                OutlinedButton(onClick = { menu = true }, enabled = active == null) {
                    Text(state.nonprofits.find { it.id == selected }?.name ?: "Choose a nonprofit")
                }
                DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
                    state.nonprofits.forEach { nonprofit -> DropdownMenuItem(text = { Text(nonprofit.name) }, onClick = { selected = nonprofit.id; menu = false }) }
                }
            } }
            item { OutlinedTextField(notes, { notes = it }, Modifier.fillMaxWidth(), label = { Text("Notes (optional)") }, enabled = active == null) }
            item {
                val seconds = active?.let { Duration.between(Instant.parse(it.startTimeUtc), now).seconds.coerceAtLeast(0) } ?: 0
                Text(if (active == null) "Ready when you are" else "${active.nonprofitName}: ${elapsed(seconds)}", style = MaterialTheme.typography.headlineSmall)
            }
            item { Button(onClick = { action {
                if (active != null) { tracker.stop(); notes = "" } else selected?.let { tracker.start(it, notes) }
            } }, modifier = Modifier.fillMaxWidth(), enabled = active != null || selected != null,
                colors = ButtonDefaults.buttonColors(containerColor = if (active == null) Color(0xFF16733B) else Color(0xFFB3261E))) {
                Text(if (active == null) "Start" else "Stop")
            } }
            item { Text("Completed: %.2f hours".format(state.sessions.sumOf { it.durationSeconds ?: 0 } / 3600.0)) }
            item { OutlinedButton(onClick = { exportSnapshot = tracker.csv(); export.launch("nonprofit-hours.csv") }, enabled = state.sessions.any { it.endTimeUtc != null }) { Text("Export CSV for Google Sheets") } }
            item { Text("Timing continues when the app is closed. Reopen and press Stop to finish.") }
            error?.let { message -> item { Text(message, color = MaterialTheme.colorScheme.error) } }
            items(state.sessions.asReversed(), key = { it.sessionId }) { session ->
                HorizontalDivider()
                Text(session.nonprofitName, style = MaterialTheme.typography.titleMedium)
                Text("${session.startTimeUtc} · ${session.durationSeconds?.let(::elapsed) ?: "In progress"}")
                if (session.notes.isNotEmpty()) Text(session.notes)
            }
        }
    }
}
private fun elapsed(seconds: Long) = "%02d:%02d:%02d".format(seconds / 3600, seconds % 3600 / 60, seconds % 60)
