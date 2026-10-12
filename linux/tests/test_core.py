import copy
import csv
from datetime import datetime, timedelta, timezone, date
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tick.core import StorageLocation, FileStore, Tracker, data_path, elapsed, period_bounds


class TrackerTests(unittest.TestCase):
    def test_manual_entry_after_reload_preserves_shared_history(self):
        project = self.tracker.add_nonprofit("Kitchen")
        other = Tracker(FileStore(self.tracker.store.path))
        end = self.start + timedelta(seconds=60)
        other.add_session(project, "Remote", self.start, end)
        self.tracker.reload()
        self.assertEqual(len(self.tracker.session_conflicts(self.start, end)), 1)
        self.tracker.add_session(project, "By hand", end, end + timedelta(seconds=60))
        saved = Tracker(FileStore(self.tracker.store.path))
        self.assertEqual([s["notes"] for s in saved.state["sessions"]], ["Remote", "By hand"])

    def test_reload_reads_changes_and_keeps_state_on_failure(self):
        project = self.tracker.add_nonprofit("Kitchen")
        other = Tracker(FileStore(self.tracker.store.path))
        other.start(project, "Remote", self.start)
        before = self.tracker.store.path.read_bytes()
        self.tracker.reload()
        self.assertEqual(self.tracker.active, other.active)
        self.assertEqual(self.tracker.store.path.read_bytes(), before)
        self.tracker.stop(self.start + timedelta(seconds=60))
        self.assertEqual(Tracker(FileStore(self.tracker.store.path)).state["sessions"][0]["durationSeconds"], 60)
        previous = copy.deepcopy(self.tracker.state)
        self.tracker.store.path.write_text("invalid")
        with self.assertRaises(ValueError):
            self.tracker.reload()
        self.assertEqual(self.tracker.state, previous)
        self.tracker.store.path.unlink()
        with self.assertRaises(FileNotFoundError):
            self.tracker.reload()
        self.assertEqual(self.tracker.state, previous)

    def test_session_conflicts(self):
        first = self.tracker.add_nonprofit("Kitchen")
        second = self.tracker.add_nonprofit("Board")
        def time(seconds):
            return self.start + timedelta(seconds=seconds)
        self.tracker.add_session(first, "Meals", time(100), time(200))
        for start, end, expected in [(50, 150, 50), (150, 250, 50), (125, 175, 50), (50, 250, 100), (100, 200, 100), (0, 100, 0), (200, 300, 0)]:
            with self.subTest(start=start, end=end):
                conflicts = self.tracker.session_conflicts(time(start), time(end))
                self.assertEqual(len(conflicts), int(expected > 0))
                if expected:
                    self.assertEqual(conflicts[0]["overlap"], expected)
                    self.assertEqual(conflicts[0]["duration"], 100)
                    self.assertEqual(conflicts[0]["start"], time(max(start, 100)))
                    self.assertEqual(conflicts[0]["end"], time(min(end, 200)))
                    self.assertEqual(conflicts[0]["session"]["notes"], "Meals")
        self.tracker.add_session(second, "Meeting", time(150), time(300))
        conflicts = self.tracker.session_conflicts(time(175), time(225))
        self.assertEqual([c["overlap"] for c in conflicts], [25, 50])
        self.assertEqual({c["session"]["project"] for c in conflicts}, {"Kitchen", "Board"})
        self.assertEqual(self.tracker.session_conflicts(time(225), time(175)), [])
        self.assertEqual(len(Tracker(FileStore(self.path)).state["sessions"]), 2)
        self.tracker.start(first, "Running", time(400))
        active = self.tracker.session_conflicts(time(425), time(600), now=time(500))
        self.assertEqual(active[0]["overlap"], 75)
        self.assertEqual(active[0]["duration"], 100)

    def test_start_reloads_remote_history_and_active_session(self):
        project = self.tracker.add_nonprofit("Kitchen")
        other = Tracker(FileStore(self.path))
        other.start(project, "Remote", self.start)
        before = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, "Stop the current session"):
            self.tracker.start(project, "Local", self.start)
        self.assertEqual(self.tracker.active, other.active)
        self.assertEqual(self.path.read_bytes(), before)
        other.stop(self.start + timedelta(seconds=60))
        self.tracker.start(project, "Local", self.start + timedelta(seconds=120))
        saved = Tracker(FileStore(self.path))
        self.assertEqual([s["notes"] for s in saved.state["sessions"]], ["Remote", "Local"])
        self.assertEqual(saved.state["sessions"][0]["durationSeconds"], 60)

    def test_start_rejects_removed_project_and_unreadable_file(self):
        project = self.tracker.add_nonprofit("Kitchen")
        latest = copy.deepcopy(self.tracker.state)
        latest["nonprofits"] = []
        self.path.write_text(json.dumps(latest))
        before = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, "Select a project"):
            self.tracker.start(project)
        self.assertEqual(self.path.read_bytes(), before)
        for raw in (b"broken", None):
            if raw is None:
                self.path.unlink()
            else:
                self.path.write_bytes(raw)
            with self.assertRaises((ValueError, OSError)):
                self.tracker.start(project)
            self.assertEqual(self.tracker.state, latest)
            self.assertEqual(self.path.read_bytes() if self.path.exists() else None, raw)

    def test_edit_times_updates_reports_and_preserves_state_on_failure(self):
        nonprofit = self.tracker.add_nonprofit("Kitchen")
        self.tracker.add_session(nonprofit, "Meals", self.start, self.start + timedelta(hours=1))
        original = copy.deepcopy(self.tracker.state["sessions"][0])
        session_id = original["sessionId"]
        self.tracker.start(nonprofit, "Active", self.start + timedelta(days=2))
        active = copy.deepcopy(self.tracker.active)
        start = self.start - timedelta(days=1)
        self.tracker.update_times(session_id, start, start + timedelta(minutes=30), self.start)
        saved = Tracker(FileStore(self.path)).state["sessions"][0]
        self.assertEqual(1800, saved["durationSeconds"])
        self.assertEqual(original["sessionId"], saved["sessionId"])
        self.assertEqual(original["notes"], saved["notes"])
        self.assertEqual(active, self.tracker.active)
        self.assertIn("00:30:00", self.tracker.clipboard_text())
        self.assertIn("1800", self.tracker.csv())
        before = copy.deepcopy(self.tracker.state)
        disk = self.path.read_bytes()
        for selected, end in [(session_id, start), (session_id, start - timedelta(seconds=1)),
                              (active["sessionId"], start + timedelta(hours=1)), ("missing", start + timedelta(hours=1))]:
            with self.assertRaises(ValueError):
                self.tracker.update_times(selected, start, end)
        with patch.object(self.tracker.store, "save", side_effect=OSError("Disk full")):
            with self.assertRaises(OSError):
                self.tracker.update_times(session_id, start, start + timedelta(hours=2))
        self.assertEqual(before, self.tracker.state)
        self.assertEqual(disk, self.path.read_bytes())

    def test_every_write_orders_saved_sessions_by_start(self):
        nonprofit = self.tracker.add_nonprofit("Kitchen")
        self.tracker.start(nonprofit, "Active", self.start + timedelta(days=2))
        self.tracker.add_session(nonprofit, "Later", self.start + timedelta(days=1), self.start + timedelta(days=1, hours=1))
        self.tracker.add_session(nonprofit, "Earlier", self.start, self.start + timedelta(hours=1))
        original = copy.deepcopy(self.tracker.state)
        saved = json.loads(self.path.read_bytes())
        self.assertEqual(["Earlier", "Later", "Active"], [s["notes"] for s in saved["sessions"]])
        self.assertEqual(original, self.tracker.state)
        self.tracker.update_notes(saved["sessions"][0]["sessionId"], "Edited")
        saved = json.loads(self.path.read_bytes())
        self.assertEqual(["Edited", "Later", "Active"], [s["notes"] for s in saved["sessions"]])

    def test_capitalizes_new_and_edited_activities(self):
        nonprofit = self.tracker.add_nonprofit("kitchen")
        self.assertEqual("Kitchen", self.tracker.state["nonprofits"][0]["name"])
        self.tracker.start(nonprofit, "  emails, google Fi\n990-EZ review", self.start)
        self.assertEqual("  Emails, Google Fi\n990-EZ review", self.tracker.active["notes"])
        self.tracker.stop(self.start + timedelta(hours=1))
        self.tracker.update_notes(self.tracker.state["sessions"][0]["sessionId"], 'collect payments\r\n"annual meeting",MN DOT')
        self.assertEqual('Collect payments\r\n"Annual meeting",MN DOT', self.tracker.state["sessions"][0]["notes"])
        self.tracker.add_session(nonprofit, "cooking,etc", self.start, self.start + timedelta(minutes=15))
        self.assertEqual("Cooking,Etc", self.tracker.state["sessions"][-1]["notes"])

    def test_delete_only_short_completed_sessions(self):
        nonprofit = self.tracker.add_nonprofit("Kitchen")
        for seconds in (0, 59, 60):
            self.tracker.start(nonprofit, "Short", self.start)
            session_id = self.tracker.active["sessionId"]
            with self.assertRaises(ValueError):
                self.tracker.delete_session(session_id)
            self.tracker.stop(self.start + timedelta(seconds=seconds))
            original = copy.deepcopy(self.tracker.state)
            if seconds < 60:
                with patch.object(self.tracker.store, "save", side_effect=OSError("Disk full")):
                    with self.assertRaises(OSError):
                        self.tracker.delete_session(session_id)
                self.assertEqual(original, self.tracker.state)
                self.tracker.delete_session(session_id)
                self.assertEqual([], Tracker(FileStore(self.path)).state["sessions"])
                self.assertEqual("", self.tracker.clipboard_text())
                self.assertNotIn("Short", self.tracker.csv())
            else:
                with self.assertRaises(ValueError):
                    self.tracker.delete_session(session_id)
        with self.assertRaises(ValueError):
            self.tracker.delete_session("missing")

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
        for notes, expected in [("", "No notes   00:23:43"), (" \t\r\n ", "No notes   00:23:43"),
                                ("Annual meeting, Google Fi,Cooking,Etc", "Annual meeting   00:05:56\nCooking   00:05:56\nEtc   00:05:55\nGoogle Fi   00:05:56"),
                                ("Meals,, Meals, ", "Meals   00:23:43"), (", ,", "No notes   00:23:43"),
                                ("Annual meeting\nGoogle Fi", "Annual meeting   00:11:52\nGoogle Fi   00:11:51"),
                                ("Annual meeting\rGoogle Fi", "Annual meeting   00:11:52\nGoogle Fi   00:11:51"),
                                (" Annual meeting\r\n \r\nGoogle Fi ", "Annual meeting   00:11:52\nGoogle Fi   00:11:51")]:
            with self.subTest(notes=notes):
                self.tracker.update_notes(session_id, notes)
                self.assertEqual(self.tracker.clipboard_text(), f"NEST 00:23:43:\n{expected}")
                self.assertEqual(self.tracker.state["sessions"][0]["notes"], notes)
    def test_summary_uses_project_id_instead_of_stale_session_name(self):
        family = self.tracker.add_nonprofit("Family")
        volunteer = self.tracker.add_nonprofit("Volunteer")
        self.tracker.add_session(family, "Cake", self.start, self.start + timedelta(seconds=60))
        self.tracker.add_session(volunteer, "Donations", self.start + timedelta(seconds=60), self.start + timedelta(seconds=180))
        stored = copy.deepcopy(self.tracker.state)
        stored["sessions"][1]["project"] = "Family"
        self.tracker.commit(stored)
        restored = Tracker(FileStore(self.path))
        before = self.path.read_bytes()
        expected = "Family 00:01:00:\nCake   00:01:00\n\nVolunteer 00:02:00:\nDonations   00:02:00"
        self.assertEqual(restored.clipboard_text(), expected)
        self.assertEqual(restored.clipboard_text("Weekly", self.start.date(), timezone.utc), expected)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(restored.state["sessions"][1]["project"], "Family")

    def test_clipboard_combines_descriptions_and_sorts_alphabetically(self):
        kitchen = self.tracker.add_nonprofit("Kitchen")
        garden = self.tracker.add_nonprofit("Garden")
        start = self.start
        for nonprofit, notes, seconds in [(kitchen, "Meals", 3600), (garden, "Planting", 1800), (kitchen, "Cleanup", 2700), (kitchen, " Cleanup ", 60), (kitchen, "", 1), (kitchen, " \n ", 2), (garden, "Cleanup", 120)]:
            self.tracker.start(nonprofit, notes, start)
            start += timedelta(seconds=seconds)
            self.tracker.stop(start)
        self.assertEqual(self.tracker.clipboard_text(),
                         "Kitchen 01:46:03:\nCleanup   00:46:00\nMeals   01:00:00\nNo notes   00:00:03\n\nGarden 00:32:00:\nCleanup   00:02:00\nPlanting   00:30:00")
        self.assertEqual(len(self.tracker.export_sessions()), 7)
        self.assertIn(" Cleanup ", self.tracker.csv())
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
        notes = 'Meals, "Served"\nCleanup 🍲'
        for offset, duration, text in [(-1, 1, "Outside"), (0, 90000, notes), (86400, 60, "End boundary")]:
            self.tracker.start(nonprofit, text, start + timedelta(seconds=offset))
            self.tracker.stop(start + timedelta(seconds=offset + duration))
        self.tracker.start(nonprofit, "Active", start + timedelta(minutes=2))
        zone = timezone(timedelta(hours=2))
        day = date(2025, 1, 1)
        rows = list(csv.DictReader(io.StringIO(self.tracker.csv("Daily", day, zone))))
        self.assertEqual([row["notes"] for row in rows], [notes])
        self.assertEqual(self.tracker.clipboard_text("Daily", day, zone), 'Kitchen 25:00:00:\n"Served"   08:20:00\nCleanup 🍲   08:20:00\nMeals   08:20:00')
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
        self.assertEqual(session["projectId"], nonprofit)
        self.assertEqual(session["platform"], "linux")
        self.assertEqual(elapsed(session["durationSeconds"]), "27:00:00")

    def test_edit_notes_preserves_hours_and_survives_restart(self):
        nonprofit = self.tracker.add_nonprofit("Kitchen")
        self.tracker.start(nonprofit, "Original", self.start)
        self.tracker.stop(self.start + timedelta(hours=1))
        original = copy.deepcopy(self.tracker.state["sessions"][0])
        for notes in ('Meals, "Served"\nCleanup 🍲', ''):
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
        with patch("tick.core.os.replace", side_effect=OSError("Disk full")):
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
        self.tracker.start(nonprofit, 'A, "Quote"\nAnd a newline', self.start)
        self.assertEqual(len(list(csv.reader(io.StringIO(self.tracker.csv())))), 1)
        self.tracker.stop(self.start + timedelta(hours=1))
        rows = list(csv.DictReader(io.StringIO(self.tracker.csv())))
        self.assertEqual(rows[0]["project"], "'=SUM(1,2)")
        self.assertEqual(list(rows[0]), ["project", "startTimeUtc", "endTimeUtc", "durationSeconds", "hours", "notes", "deviceId", "platform"])
        self.assertNotIn(None, rows[0])
        self.assertEqual(rows[0]["notes"], 'A, "Quote"\nAnd a newline')
        self.assertEqual(rows[0]["hours"], "1.0")
        self.assertEqual(rows[0]["startTimeUtc"], "2026-01-01T00:00:00Z")
        self.assertEqual(self.tracker.state["sessions"][0]["syncState"], "pending")

    def test_xdg_location_and_relative_fallback(self):
        with patch.dict("os.environ", {"XDG_DATA_HOME": self.directory.name}):
            self.assertEqual(data_path(), Path(self.directory.name) / "time-is-clearly-kept/tick.json")
        with patch.dict("os.environ", {"XDG_DATA_HOME": "relative"}):
            self.assertEqual(data_path(), Path.home() / ".local/share/time-is-clearly-kept/tick.json")

    def test_naive_timestamp_is_rejected(self):
        nonprofit = self.tracker.add_nonprofit("Kitchen")
        with self.assertRaises(ValueError):
            self.tracker.start(nonprofit, now=datetime(2026, 1, 1))
        self.assertIsNone(self.tracker.active)


class FirstRunStorageTests(unittest.TestCase):
    def test_first_run_requires_location_then_creates_and_reopens_tick(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            storage = StorageLocation(root / "location.json")
            with patch("tick.core.data_path", return_value=root / "default" / "tick.json"):
                with self.assertRaises(FileNotFoundError):
                    storage.open()
                self.assertFalse((root / "default").exists())
            tracker = storage.select(root)
            self.assertTrue((root / "tick.json").exists())
            self.assertEqual(storage.open().state, tracker.state)
            tracker.add_nonprofit("Kitchen")
            self.assertEqual(storage.select(root).state, tracker.state)

    def test_invalid_file_is_not_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "tick.json").write_text("invalid")
            storage = StorageLocation(root / "location.json")
            with self.assertRaises(ValueError):
                storage.select(root)
            self.assertEqual((root / "tick.json").read_text(), "invalid")
            self.assertFalse((root / "location.json").exists())


if __name__ == "__main__":
    unittest.main()
