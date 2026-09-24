"""Tracking and storage independent of GTK; timestamps follow the shared schema."""
import copy
import csv
import io
import json
import os
from pathlib import Path
import tempfile
from datetime import datetime, timezone
from uuid import uuid4


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


class FileStore:
    def __init__(self, path):
        self.path = Path(path)

    def load(self):
        if not self.path.exists():
            return {"deviceId": str(uuid4()), "nonprofits": [], "sessions": []}
        state = json.loads(self.path.read_text(encoding="utf-8"))
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
                duration = int(seconds)
                if seconds < 0 or type(session.get("durationSeconds")) is not int or session["durationSeconds"] != duration:
                    raise ValueError("Invalid saved duration.")
        if active > 1:
            raise ValueError("Multiple active sessions in saved file.")
        return state

    def save(self, state):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        name = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent, delete=False) as stream:
                name = stream.name
                json.dump(state, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
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

    def csv(self):
        fields = ["sessionId", "nonprofitId", "nonprofitName", "startTimeUtc", "endTimeUtc",
                  "durationSeconds", "hours", "notes", "deviceId", "platform", "updatedAtUtc"]
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(fields)
        for session in self.state["sessions"]:
            if session.get("endTimeUtc") is None:
                continue
            row = dict(session, hours=session["durationSeconds"] / 3600)
            values = []
            for key in fields:
                value = str(row[key])
                if value.lstrip().startswith(("=", "+", "-", "@")):
                    value = "'" + value
                values.append(value)
            writer.writerow(values)
        return output.getvalue()


def elapsed(seconds):
    seconds = max(0, int(seconds))
    return f"{seconds // 3600:02}:{seconds % 3600 // 60:02}:{seconds % 60:02}"
