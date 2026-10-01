"""Tracking and storage independent of GTK; timestamps follow the shared schema."""
import copy
import csv
import io
import json
import os
from pathlib import Path
import tempfile
from datetime import datetime, timezone, timedelta
from uuid import uuid4, UUID


def timestamp(value=None):
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is None:
        raise ValueError("Timestamp must include a timezone.")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse(value):
    date = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if date.tzinfo is None:
        raise ValueError("Saved timestamp must include a timezone.")
    return date


def data_path():
    root = os.environ.get("XDG_DATA_HOME", "")
    base = Path(root) if root and Path(root).is_absolute() else Path.home() / ".local/share"
    return base / "nonprofit-hours/sessions.json"


def decode_data(raw):
    state = json.loads(raw)
    if not isinstance(state, dict):
        raise ValueError("Invalid data file.")
    legacy = "schemaVersion" not in state
    if state.get("schemaVersion", 1) != 1:
        raise ValueError("Unsupported data file version.")
    state["schemaVersion"] = 1
    state["deviceId"] = str(UUID(state["deviceId"]))
    for nonprofit in state["nonprofits"]:
        nonprofit["id"] = str(UUID(nonprofit["id"]))
    for session in state["sessions"]:
        for key in ("sessionId", "nonprofitId", "deviceId"):
            session[key] = str(UUID(session[key]))
        if legacy:
            session.setdefault("platform", "android")
            session.setdefault("syncState", "pending")
            for key in ("startTimeUtc", "endTimeUtc", "updatedAtUtc"):
                value = session.get(key)
                if type(value) in (int, float):
                    session[key] = timestamp(datetime(2001, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=value))
        session.setdefault("endTimeUtc", None)
        session.setdefault("durationSeconds", None)
        if session.get("platform") not in ("android", "ios", "macos", "windows", "linux") or session.get("syncState") not in ("pending", "synced", "failed"):
            raise ValueError("Invalid session platform or sync state.")
    # Refuse malformed state rather than overwriting an unreadable history.
    if not isinstance(state, dict) or not isinstance(state.get("deviceId"), str):
        raise ValueError("Invalid saved device identity.")
    for key in ("nonprofits", "sessions"):
        if not isinstance(state.get(key), list):
            raise ValueError("Invalid saved " + key)
    ids = set()
    for nonprofit in state["nonprofits"]:
        if not isinstance(nonprofit.get("id"), str) or not isinstance(nonprofit.get("name"), str) or nonprofit["id"] in ids:
            raise ValueError("Invalid saved nonprofit.")
        ids.add(nonprofit["id"])
    sessions = set()
    active = 0
    for session in state["sessions"]:
        for key in ("sessionId", "nonprofitId", "nonprofitName", "startTimeUtc", "notes", "deviceId", "platform", "updatedAtUtc", "syncState"):
            if not isinstance(session.get(key), str):
                raise ValueError("Invalid saved session field: " + key)
        if session["sessionId"] in sessions or session["nonprofitId"] not in ids:
            raise ValueError("Invalid saved session identity.")
        sessions.add(session["sessionId"])
        start = parse(session["startTimeUtc"])
        parse(session["updatedAtUtc"])
        if session.get("endTimeUtc") is None:
            active += 1
            if session.get("durationSeconds") is not None:
                raise ValueError("Active session has a duration.")
        else:
            seconds = (parse(session["endTimeUtc"]) - start).total_seconds()
            if seconds < 0 or type(session.get("durationSeconds")) is not int or session["durationSeconds"] < 0 or abs(session["durationSeconds"] - seconds) >= 1.01:
                raise ValueError("Invalid saved duration.")
    if active > 1:
        raise ValueError("Multiple active sessions in saved file.")
    return state

class FileStore:
    def __init__(self, path, require_existing=False):
        self.path = Path(path)
        self.require_existing = require_existing
        self.snapshot = None

    def load(self):
        if not self.path.exists() and not self.require_existing:
            self.snapshot = None
            return {"schemaVersion": 1, "deviceId": str(uuid4()), "nonprofits": [], "sessions": []}
        raw = self.path.read_bytes()
        state = decode_data(raw)
        self.snapshot = raw
        return state

    def save(self, state):
        current = self.path.read_bytes() if self.path.exists() else None
        if current != self.snapshot:
            raise ValueError("The data file changed or was removed. Select its data folder again before saving.")
        raw = json.dumps(state, ensure_ascii=False).encode("utf-8")
        decode_data(raw)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        name = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent, delete=False) as stream:
                name = stream.name
                json.dump(state, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
            self.snapshot = raw
        finally:
            if name and os.path.exists(name):
                os.unlink(name)


class Tracker:
    def __init__(self, store):
        self.store = store
        self.state = store.load()

    @property
    def active(self):
        return next((s for s in self.state["sessions"] if s.get("endTimeUtc") is None), None)

    def commit(self, state):
        self.store.save(state)
        self.state = state

    def add_nonprofit(self, name):
        name = name.strip()
        if not name or any(n["name"].casefold() == name.casefold() for n in self.state["nonprofits"]):
            raise ValueError("Enter a unique nonprofit name.")
        nonprofit = {"id": str(uuid4()), "name": name}
        state = copy.deepcopy(self.state)
        state["nonprofits"].append(nonprofit)
        self.commit(state)
        return nonprofit["id"]

    def start(self, nonprofit_id, notes="", now=None):
        if self.active:
            raise ValueError("Stop the current session first.")
        nonprofit = next((n for n in self.state["nonprofits"] if n["id"] == nonprofit_id), None)
        if nonprofit is None:
            raise ValueError("Select a nonprofit first.")
        date = timestamp(now)
        state = copy.deepcopy(self.state)
        state["sessions"].append({"sessionId": str(uuid4()), "nonprofitId": nonprofit_id,
            "nonprofitName": nonprofit["name"], "startTimeUtc": date, "endTimeUtc": None,
            "durationSeconds": None, "notes": notes, "deviceId": state["deviceId"],
            "platform": "linux", "updatedAtUtc": date, "syncState": "pending"})
        self.commit(state)

    def add_session(self, nonprofit_id, notes, start, end, now=None):
        nonprofit = next((n for n in self.state["nonprofits"] if n["id"] == nonprofit_id), None)
        if nonprofit is None:
            raise ValueError("Select a nonprofit.")
        if not notes.strip():
            raise ValueError("Enter what you worked on.")
        start_text, end_text = timestamp(start), timestamp(end)
        seconds = (parse(end_text) - parse(start_text)).total_seconds()
        if seconds <= 0:
            raise ValueError("End must be after start.")
        state = copy.deepcopy(self.state)
        state["sessions"].append({"sessionId": str(uuid4()), "nonprofitId": nonprofit_id,
            "nonprofitName": nonprofit["name"], "startTimeUtc": start_text, "endTimeUtc": end_text,
            "durationSeconds": int(seconds), "notes": notes, "deviceId": state["deviceId"],
            "platform": "linux", "updatedAtUtc": timestamp(now), "syncState": "pending"})
        self.commit(state)

    def update_notes(self, session_id, notes, now=None):
        state = copy.deepcopy(self.state)
        session = next((s for s in state["sessions"] if s["sessionId"] == session_id), None)
        if session is None:
            raise ValueError("The session could not be found.")
        session.update(notes=notes, updatedAtUtc=timestamp(now), syncState="pending")
        self.commit(state)

    def stop(self, now=None):
        if not self.active:
            raise ValueError("There is no active session.")
        date = timestamp(now)
        seconds = (parse(date) - parse(self.active["startTimeUtc"])).total_seconds()
        if seconds < 0:
            raise ValueError("Correct the system clock before stopping.")
        state = copy.deepcopy(self.state)
        session = next(s for s in state["sessions"] if s["sessionId"] == self.active["sessionId"])
        session.update(endTimeUtc=date, durationSeconds=int(seconds), updatedAtUtc=date)
        self.commit(state)

    def export_sessions(self, period=None, day=None, zone=None):
        bounds = period_bounds(period, day) if period else None
        return sorted((s for s in self.state["sessions"] if s.get("endTimeUtc") is not None
                       and (bounds is None or bounds[0] <= parse(s["startTimeUtc"]).astimezone(zone).date() < bounds[1])),
                      key=lambda s: parse(s["startTimeUtc"]))

    def clipboard_text(self, period=None, day=None, zone=None):
        def activities(value):
            return [part.strip() for line in value.splitlines() for part in line.split(",") if part.strip()] or ["No notes"]

        groups = {}
        for session in self.export_sessions(period, day, zone):
            groups.setdefault(session["nonprofitId"], []).append(session)
        summaries = []
        for sessions in groups.values():
            descriptions = {}
            for session in sessions:
                names = activities(session["notes"])
                share, remainder = divmod(session["durationSeconds"], len(names))
                for index, name in enumerate(names):
                    descriptions[name] = descriptions.get(name, 0) + share + (index < remainder)
            lines = [f"{name}   {elapsed(descriptions[name])}"
                     for name in sorted(descriptions, key=lambda name: (name.lower(), name))]
            summaries.append(f"{sessions[0]['nonprofitName']} {elapsed(sum(s['durationSeconds'] for s in sessions))}:\n" + "\n".join(lines))
        return "\n\n".join(summaries)

    def csv(self, period=None, day=None, zone=None):
        fields = ["nonprofitName", "startTimeUtc", "endTimeUtc",
                  "durationSeconds", "hours", "notes", "deviceId", "platform"]
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(fields)
        for session in self.export_sessions(period, day, zone):
            row = dict(session, hours=session["durationSeconds"] / 3600)
            values = []
            for key in fields:
                value = str(row[key])
                if value.lstrip().startswith(("=", "+", "-", "@")):
                    value = "'" + value
                values.append(value)
            writer.writerow(values)
        return output.getvalue()


def period_bounds(period, day):
    if period == "Daily":
        return day, day + timedelta(days=1)
    if period == "Weekly":
        start = day - timedelta(days=day.weekday())
        return start, start + timedelta(days=7)
    if period == "Monthly":
        start = day.replace(day=1)
        return start, (start + timedelta(days=32)).replace(day=1)
    raise ValueError("Choose Daily, Weekly, or Monthly.")


def elapsed(seconds):
    seconds = max(0, int(seconds))
    return f"{seconds // 3600:02}:{seconds % 3600 // 60:02}:{seconds % 60:02}"


class StorageLocation:
    def __init__(self, settings=None):
        root = os.environ.get("XDG_CONFIG_HOME", "")
        base = Path(root) if root and Path(root).is_absolute() else Path.home() / ".config"
        self.settings = Path(settings) if settings else base / "nonprofit-hours/location.json"

    def open(self):
        if not self.settings.exists():
            return Tracker(FileStore(data_path()))
        path = json.loads(self.settings.read_text(encoding="utf-8"))["path"]
        return Tracker(FileStore(path, require_existing=True))

    def select(self, folder, current=None):
        path = Path(folder).absolute() / "nonprofit-hours.json"
        if not path.exists() and current is not None:
            # Initialize the configured folder, keeping the previous file intact.
            destination = FileStore(path)
            destination.snapshot = path.read_bytes() if path.exists() else None
            destination.save(copy.deepcopy(current.state))
        next_tracker = Tracker(FileStore(path, require_existing=True))
        self.settings.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.settings.parent, delete=False) as stream:
                temporary = stream.name
                json.dump({"path": str(path)}, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.settings)
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)
        return next_tracker
