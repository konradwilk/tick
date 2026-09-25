import copy
import csv
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from nonprofit_hours.core import FileStore, Tracker, data_path, elapsed


class TrackerTests(unittest.TestCase):
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
