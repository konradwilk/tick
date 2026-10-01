import copy
import csv
from datetime import datetime, timedelta, timezone, date
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from nonprofit_hours.core import FileStore, Tracker, data_path, elapsed, period_bounds


class TrackerTests(unittest.TestCase):
    def test_manual_session_persists_exports_and_preserves_timer(self):
        nonprofit = self.tracker.add_nonprofit("Kitchen")
        self.tracker.start(nonprofit, "Active", self.start)
        active = copy.deepcopy(self.tracker.active)
        end = self.start + timedelta(hours=2)
        self.tracker.add_session(nonprofit, "Meals", self.start, end)
        restored = Tracker(FileStore(self.tracker.store.path))
        self.assertEqual(restored.state, self.tracker.state)
        self.assertEqual(self.tracker.active, active)
        self.assertEqual(self.tracker.export_sessions()[0]["durationSeconds"], 7200)
        self.assertIn("Meals", self.tracker.csv())
        self.assertEqual(self.tracker.clipboard_text(), "Kitchen 02:00:00:\nMeals   02:00:00")
        original = copy.deepcopy(self.tracker.state)
        for args in [(nonprofit, "Meals", end, self.start), (nonprofit, "Meals", self.start, self.start),
                     (nonprofit, " ", self.start, end), ("missing", "Meals", self.start, end)]:
            with self.assertRaises(ValueError):
                self.tracker.add_session(*args)
        with patch.object(self.tracker.store, "save", side_effect=OSError("Disk full")):
            with self.assertRaises(OSError):
                self.tracker.add_session(nonprofit, "Meals", self.start, end)
        self.assertEqual(original, self.tracker.state)

    def test_clipboard_normalizes_notes_without_changing_stored_text(self):
        nonprofit = self.tracker.add_nonprofit("NEST")
        self.tracker.start(nonprofit, now=self.start)
        self.tracker.stop(self.start + timedelta(seconds=1423))
        session_id = self.tracker.state["sessions"][0]["sessionId"]
        for notes, expected in [("", "No notes"), (" \t\r\n ", "No notes"),
                                ("Annual meeting\nGoogle Fi", "Annual meeting, Google Fi"),
                                ("Annual meeting\rGoogle Fi", "Annual meeting, Google Fi"),
                                (" Annual meeting\r\n \r\nGoogle Fi ", "Annual meeting, Google Fi")]:
            with self.subTest(notes=notes):
                self.tracker.update_notes(session_id, notes)
                self.assertEqual(self.tracker.clipboard_text(), f"NEST 00:23:43:\n{expected}   00:23:43")
                self.assertEqual(self.tracker.state["sessions"][0]["notes"], notes)
    def test_clipboard_groups_totals_and_lists_each_note_in_time_order(self):
        kitchen = self.tracker.add_nonprofit("Kitchen")
        garden = self.tracker.add_nonprofit("Garden")
        start = self.start
        for nonprofit, notes, seconds in [(kitchen, "Meals", 3600), (garden, "Planting", 1800), (kitchen, "Cleanup", 2700)]:
            self.tracker.start(nonprofit, notes, start)
            start += timedelta(seconds=seconds)
            self.tracker.stop(start)
        self.assertEqual(self.tracker.clipboard_text(),
                         "Kitchen 01:45:00:\nMeals   01:00:00\nCleanup   00:45:00\n\nGarden 00:30:00:\nPlanting   00:30:00")
    def test_export_period_boundaries(self):
        for period, day, start, end in [
            ("Daily", "2024-02-29", "2024-02-29", "2024-03-01"),
            ("Weekly", "2025-01-01", "2024-12-30", "2025-01-06"),
            ("Weekly", "2025-01-05", "2024-12-30", "2025-01-06"),
            ("Monthly", "2024-12-12", "2024-12-01", "2025-01-01")]:
            self.assertEqual(period_bounds(period, date.fromisoformat(day)),
                             (date.fromisoformat(start), date.fromisoformat(end)))

    def test_exports_and_clipboard_use_local_start_dates(self):
        nonprofit = self.tracker.add_nonprofit("Kitchen")
        start = datetime(2024, 12, 31, 22, tzinfo=timezone.utc)
        notes = 'Meals, "served"\nCleanup 🍲'
        for offset, duration, text in [(-1, 1, "Outside"), (0, 90000, notes), (86400, 60, "End boundary")]:
            self.tracker.start(nonprofit, text, start + timedelta(seconds=offset))
            self.tracker.stop(start + timedelta(seconds=offset + duration))
        self.tracker.start(nonprofit, "Active", start + timedelta(minutes=2))
        zone = timezone(timedelta(hours=2))
        day = date(2025, 1, 1)
        rows = list(csv.DictReader(io.StringIO(self.tracker.csv("Daily", day, zone))))
        self.assertEqual([row["notes"] for row in rows], [notes])
        self.assertEqual(self.tracker.clipboard_text("Daily", day, zone), 'Kitchen 25:00:00:\nMeals, "served", Cleanup 🍲   25:00:00')
        self.assertEqual(self.tracker.clipboard_text("Daily", date(2025, 1, 3), zone), "")
        self.assertEqual(len(self.tracker.export_sessions("Monthly", day, zone)), 2)
        self.assertEqual(len(self.tracker.export_sessions("Weekly", day, zone)), 3)
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "sessions.json"
        self.store = FileStore(self.path)
        self.tracker = Tracker(self.store)
        self.start = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def test_restart_retains_session_identity_and_elapsed_time(self):
        nonprofit = self.tracker.add_nonprofit("Kitchen")
        self.tracker.start(nonprofit, "Dinner", self.start)
        session_id = self.tracker.active["sessionId"]
        restored = Tracker(self.store)
        self.assertEqual(restored.active["sessionId"], session_id)
        self.assertEqual(restored.active["notes"], "Dinner")
        restored.stop(self.start + timedelta(hours=27))
        loaded = Tracker(self.store)
        self.assertIsNone(loaded.active)
        session = loaded.state["sessions"][0]
        self.assertEqual(session["durationSeconds"], 27 * 3600)
        self.assertEqual(session["nonprofitId"], nonprofit)
        self.assertEqual(session["platform"], "linux")
        self.assertEqual(elapsed(session["durationSeconds"]), "27:00:00")

    def test_edit_notes_preserves_hours_and_survives_restart(self):
        nonprofit = self.tracker.add_nonprofit("Kitchen")
        self.tracker.start(nonprofit, "Original", self.start)
        self.tracker.stop(self.start + timedelta(hours=1))
        original = copy.deepcopy(self.tracker.state["sessions"][0])
        for notes in ('Meals, "served"\nCleanup 🍲', ''):
            self.tracker.update_notes(original["sessionId"], notes, self.start)
            expected = dict(original, notes=notes, updatedAtUtc=original["startTimeUtc"], syncState="pending")
            self.assertEqual(Tracker(FileStore(self.path)).state["sessions"][0], expected)
            self.assertEqual(list(csv.DictReader(io.StringIO(self.tracker.csv())))[0]["notes"], notes)
        before = self.path.read_bytes()
        state = copy.deepcopy(self.tracker.state)
        with patch.object(self.store, "save", side_effect=OSError("Read only")):
            with self.assertRaises(OSError):
                self.tracker.update_notes(original["sessionId"], "Unsaved")
        with self.assertRaises(ValueError):
            self.tracker.update_notes("missing", "Unsaved")
        self.assertEqual(self.tracker.state, state)
        self.assertEqual(self.path.read_bytes(), before)

    def test_invalid_actions_preserve_state(self):
        with self.assertRaises(ValueError):
            self.tracker.add_nonprofit("  ")
        nonprofit = self.tracker.add_nonprofit(" Kitchen ")
        with self.assertRaises(ValueError):
            self.tracker.add_nonprofit("KITCHEN")
        with self.assertRaises(ValueError):
            self.tracker.stop()
        with self.assertRaises(ValueError):
            self.tracker.start("unknown")
        self.tracker.start(nonprofit, now=self.start)
        original = copy.deepcopy(self.tracker.state)
        with self.assertRaises(ValueError):
            self.tracker.start(nonprofit)
        with self.assertRaises(ValueError):
            self.tracker.stop(self.start - timedelta(microseconds=1))
        self.assertEqual(self.tracker.state, original)

    def test_failed_save_preserves_memory_and_disk(self):
        nonprofit = self.tracker.add_nonprofit("Kitchen")
        original = self.path.read_bytes()
        with patch("nonprofit_hours.core.os.replace", side_effect=OSError("Disk full")):
            with self.assertRaises(OSError):
                self.tracker.start(nonprofit, now=self.start)
        self.assertIsNone(self.tracker.active)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_failed_stop_keeps_active_session(self):
        nonprofit = self.tracker.add_nonprofit("Kitchen")
        self.tracker.start(nonprofit, now=self.start)
        with patch.object(self.store, "save", side_effect=OSError("Read only")):
            with self.assertRaises(OSError):
                self.tracker.stop(self.start + timedelta(seconds=60))
        self.assertIsNotNone(self.tracker.active)
        self.assertIsNotNone(Tracker(self.store).active)

    def test_corrupt_file_is_not_overwritten(self):
        self.path.write_text("broken")
        with self.assertRaises(ValueError):
            Tracker(self.store)
        self.assertEqual(self.path.read_text(), "broken")

    def test_structurally_invalid_history_is_rejected(self):
        nonprofit = self.tracker.add_nonprofit("Kitchen")
        self.tracker.start(nonprofit, now=self.start)
        state = copy.deepcopy(self.tracker.state)
        state["sessions"].append(dict(state["sessions"][0], sessionId="another"))
        self.path.write_text(json.dumps(state))
        with self.assertRaises(ValueError):
            Tracker(self.store)
        self.assertEqual(json.loads(self.path.read_text()), state)

    def test_csv_round_trip_and_formula_escaping(self):
        nonprofit = self.tracker.add_nonprofit("=SUM(1,2)")
        self.tracker.start(nonprofit, 'A, "quote"\nand a newline', self.start)
        self.assertEqual(len(list(csv.reader(io.StringIO(self.tracker.csv())))), 1)
        self.tracker.stop(self.start + timedelta(hours=1))
        rows = list(csv.DictReader(io.StringIO(self.tracker.csv())))
        self.assertEqual(rows[0]["nonprofitName"], "'=SUM(1,2)")
        self.assertEqual(list(rows[0]), ["nonprofitName", "startTimeUtc", "endTimeUtc", "durationSeconds", "hours", "notes", "deviceId", "platform"])
        self.assertNotIn(None, rows[0])
        self.assertEqual(rows[0]["notes"], 'A, "quote"\nand a newline')
        self.assertEqual(rows[0]["hours"], "1.0")
        self.assertEqual(rows[0]["startTimeUtc"], "2026-01-01T00:00:00Z")
        self.assertEqual(self.tracker.state["sessions"][0]["syncState"], "pending")

    def test_xdg_location_and_relative_fallback(self):
        with patch.dict("os.environ", {"XDG_DATA_HOME": self.directory.name}):
            self.assertEqual(data_path(), Path(self.directory.name) / "nonprofit-hours/sessions.json")
        with patch.dict("os.environ", {"XDG_DATA_HOME": "relative"}):
            self.assertEqual(data_path(), Path.home() / ".local/share/nonprofit-hours/sessions.json")

    def test_naive_timestamp_is_rejected(self):
        nonprofit = self.tracker.add_nonprofit("Kitchen")
        with self.assertRaises(ValueError):
            self.tracker.start(nonprofit, now=datetime(2026, 1, 1))
        self.assertIsNone(self.tracker.active)


if __name__ == "__main__":
    unittest.main()
