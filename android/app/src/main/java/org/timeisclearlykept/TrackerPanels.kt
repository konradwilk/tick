package org.timeisclearlykept

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.launch
import java.time.Instant
import java.time.Duration
import java.time.ZoneId
import java.time.format.DateTimeFormatter

@Composable internal fun CapturePanel(state: TrackerState, selected: String?, notes: String, now: Instant,
    onSelect: (String) -> Unit, onNotes: (String) -> Unit, onToggle: suspend () -> Unit, onSettings: () -> Unit) {
    var menu by remember { mutableStateOf(false) }
    val active = state.active
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Box {
            OutlinedButton(onClick = { menu = true }, enabled = active == null, modifier = Modifier.fillMaxWidth()) {
                Text("Project: " + (state.nonprofits.find { it.id == selected }?.name ?: "Choose a project"))
            }
            DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
                state.nonprofits.forEach { nonprofit ->
                    DropdownMenuItem(text = { Text(nonprofit.name) }, onClick = { onSelect(nonprofit.id); menu = false })
                }
            }
        }
        WriteButton(onClick = onToggle, enabled = active != null || selected != null, modifier = Modifier.fillMaxWidth(),
            colors = ButtonDefaults.buttonColors(containerColor = if (active == null) Color(0xFF176C45) else Color(0xFFB3261E))) {
            Text(if (active == null) "Start" else "Stop", style = MaterialTheme.typography.titleLarge)
        }
        Text(active?.let { "${it.project}: ${displayDuration(Duration.between(Instant.parse(it.startTimeUtc), now).seconds.coerceAtLeast(0))}" }
            ?: "Ready when you are", style = MaterialTheme.typography.titleMedium)
        OutlinedTextField(notes, onNotes, Modifier.fillMaxWidth(), label = { Text("What are you working on? (optional)") }, enabled = active == null, singleLine = true)
        if (state.nonprofits.isEmpty()) TextButton(onClick = onSettings) { Text("Add your first nonprofit in Settings") }
    }
}

@Composable internal fun HistoryPanel(state: TrackerState, onDelete: suspend (Session) -> Unit, onEditTimes: (Session) -> Unit, onEdit: (Session) -> Unit) {
    val expandedWeeks = remember { mutableStateMapOf<java.time.LocalDate, Boolean>() }
    val cutoff = remember { java.time.LocalDate.now().minusMonths(1) }
    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text("History", style = MaterialTheme.typography.headlineSmall)
        Text("Completed: %.2f hours".format(state.sessions.sumOf { it.durationSeconds ?: 0 } / 3600.0))
        if (state.sessions.isEmpty()) Text("Sessions will appear here.")
        val weeks = state.sessions.sortedByDescending { Instant.parse(it.startTimeUtc) }.groupBy { session ->
            val day = Instant.parse(session.startTimeUtc).atZone(ZoneId.systemDefault()).toLocalDate()
            ExportRange.forDate(ExportPeriod.Weekly, day).start
        }
        weeks.forEach { (start, sessions) ->
            val lastDay = start.plusDays(6)
            val firstFormat = DateTimeFormatter.ofPattern(if (start.year == lastDay.year) "MMM d" else "MMM d, uuuu")
            val label = "${start.format(firstFormat)} – ${lastDay.format(DateTimeFormatter.ofPattern("MMM d, uuuu"))}"
            OutlinedCard(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    val expanded = expandedWeeks[start] ?: sessions.any {
                        !Instant.parse(it.startTimeUtc).atZone(ZoneId.systemDefault()).toLocalDate().isBefore(cutoff)
                    }
                    TextButton(onClick = { expandedWeeks[start] = !expanded }, modifier = Modifier.fillMaxWidth()) {
                        Text("${if (expanded) "▾" else "▸"} $label", modifier = Modifier.semantics { heading() }, style = MaterialTheme.typography.titleSmall)
                    }
                    if (expanded) {
                        HorizontalDivider()
                        sessions.forEachIndexed { index, session ->
                            if (index > 0) HorizontalDivider()
                            Column(Modifier.fillMaxWidth()) {
                                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                                    Text(session.project, style = MaterialTheme.typography.titleMedium)
                                    Text(Instant.parse(session.startTimeUtc).atZone(ZoneId.systemDefault()).format(DateTimeFormatter.ofPattern("MMM d, yyyy HH:mm")), style = MaterialTheme.typography.bodySmall)
                                    Text(session.durationSeconds?.let(::displayDuration) ?: "In progress")
                                    Text(session.notes.ifBlank { "No notes" })
                                    if (session.endTimeUtc != null) Row {
                                        TextButton(onClick = { onEdit(session) }) { Text("Edit notes") }
                                        TextButton(onClick = { onEditTimes(session) }) { Text("Edit times") }
                                        if (session.durationSeconds != null && session.durationSeconds in 0L..59L)
                                            WriteButton(style = WriteButtonStyle.Text, onClick = { onDelete(session) }) { Text("Delete") }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable internal fun ReportPanel(period: String, date: String, range: ExportRange?, count: Int,
    preview: String, status: String, onPeriod: (String) -> Unit, onDate: (String) -> Unit,
    onExport: suspend () -> Unit, onCopy: suspend () -> Unit, exporting: Boolean = false) {
    OutlinedCard(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text("Export & copy", style = MaterialTheme.typography.headlineSmall)
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                ExportPeriod.entries.forEach { choice ->
                    FilterChip(selected = period == choice.name, onClick = { onPeriod(choice.name) }, label = { Text(choice.name) })
                }
            }
            OutlinedTextField(date, onDate, label = { Text("Date in period (YYYY-MM-DD)") },
                isError = range == null, singleLine = true, modifier = Modifier.fillMaxWidth())
            Text(range?.let { "${it.start} – ${it.end.minusDays(1)}: $count completed sessions" } ?: "Enter a valid date in YYYY-MM-DD format.")
            Text("Completed sessions by local start date. Weeks run Monday–Sunday.", style = MaterialTheme.typography.bodySmall)
            Text("Summary preview", style = MaterialTheme.typography.titleMedium)
            SelectionContainer { Text(preview.ifEmpty { "No completed sessions in this period." }, fontFamily = FontFamily.Monospace) }
            WriteButton(style = WriteButtonStyle.Outlined, onClick = onExport, enabled = count > 0, modifier = Modifier.fillMaxWidth(), externalWorking = exporting) { Text("Export CSV") }
            WriteButton(style = WriteButtonStyle.Outlined, onClick = onCopy, enabled = count > 0, modifier = Modifier.fillMaxWidth()) { Text("Copy summary") }
            if (status.isNotEmpty()) Text(status, style = MaterialTheme.typography.bodySmall)
        }
    }
}

private fun displayDuration(seconds: Long) = "%02d:%02d:%02d".format(seconds / 3600, seconds % 3600 / 60, seconds % 60)


/** Each write owns its feedback state; normal content and colors are never overwritten. */
internal enum class WriteButtonStyle { Filled, Outlined, Text }

@Composable internal fun WriteButton(
    onClick: suspend () -> Unit,
    enabled: Boolean = true,
    modifier: Modifier = Modifier,
    externalWorking: Boolean = false,
    border: androidx.compose.foundation.BorderStroke? = null,
    style: WriteButtonStyle = WriteButtonStyle.Filled,
    colors: ButtonColors? = null,
    content: @Composable RowScope.() -> Unit
) {
    var working by remember { mutableStateOf(false) }
    val busy = working || externalWorking
    val scope = rememberCoroutineScope()
    val amber = Color(0xFF9C6500)
    val click = {
            if (!busy) {
                working = true
                scope.launch {
                    try {
                        kotlinx.coroutines.delay(75)
                        onClick()
                        kotlinx.coroutines.delay(175)
                    } finally {
                        working = false
                    }
                }
            }
        }
    val palette = if (busy) ButtonDefaults.buttonColors(
            disabledContainerColor = amber, disabledContentColor = Color.White
        ) else colors ?: when (style) {
            WriteButtonStyle.Filled -> ButtonDefaults.buttonColors()
            WriteButtonStyle.Outlined -> ButtonDefaults.outlinedButtonColors()
            WriteButtonStyle.Text -> ButtonDefaults.textButtonColors()
        }
    val label: @Composable RowScope.() -> Unit = {
        if (busy) Text("Working…") else content()
    }
    when (style) {
        WriteButtonStyle.Filled -> Button(onClick = click, enabled = enabled && !busy, modifier = modifier, colors = palette, border = border, content = label)
        WriteButtonStyle.Outlined -> OutlinedButton(onClick = click, enabled = enabled && !busy, modifier = modifier, colors = palette,
            border = border ?: androidx.compose.foundation.BorderStroke(1.dp, MaterialTheme.colorScheme.outline), content = label)
        WriteButtonStyle.Text -> TextButton(onClick = click, enabled = enabled && !busy, modifier = modifier, colors = palette, content = label)
    }
}
