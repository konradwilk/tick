#!/usr/bin/env python3
"""Migrate tick.json to Google Sheets using only Python's standard library.

Run: python3 tools/migrate_to_sheets.py /path/to/tick.json
Sign in in your browser; no Apps Script deployment or access key is needed.
"""
import argparse
import os
from pathlib import Path
import sys

# Reuse the app's schema validation and API protocol, without importing GTK.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "linux"))
from tick.core import decode_data, parse
from tick.sheets import SheetsStore, GoogleSheetsAPI
from tick.google_auth import GoogleAccount


def migrate(source, store):
    """Upload only to an uninitialized destination; the revision guards races."""
    source = Path(source)
    state = decode_data(source.read_bytes())
    state["sessions"] = sorted(state["sessions"], key=lambda session: parse(session["startTimeUtc"]))
    if store.load() is not None:
        raise ValueError("The sheet already contains Tick data. Choose a new empty destination; nothing was overwritten.")
    store.save(state)
    saved = store.load(require_existing=True)
    if saved != state:
        raise ValueError("Upload completed but verification failed. Keep tick.json and inspect the sheet before retrying.")
    store.verify_tables(state)
    return state


def main(argv=None):
    parser = argparse.ArgumentParser(description="Copy tick.json into an empty Google Sheets destination. The source is never changed.")
    parser.add_argument("source", type=Path, nargs="?", help="Path to the existing tick.json")
    parser.add_argument("--spreadsheet", help="ID or URL of an uninitialized Tick spreadsheet already authorized for the app; otherwise create a new one")
    parser.add_argument("--upgrade-existing", action="store_true", help="Add readable tables to --spreadsheet without migrating a file or replacing history")
    parser.add_argument("--sign-in", action="store_true", help="Choose a Google account again instead of using the saved sign-in")
    parser.add_argument("--name", default="Time is Clearly Kept", help="Spreadsheet name for the empty destination (default: Time is Clearly Kept)")
    parser.add_argument("--dry-run", action="store_true", help="Validate and count source data without contacting Google or requiring credentials")
    args = parser.parse_args(argv)
    try:
        if args.upgrade_existing:
            if not args.spreadsheet or args.source or args.dry_run: raise ValueError('Use --upgrade-existing with --spreadsheet, without a source file or --dry-run.')
        elif args.source is None: raise ValueError('Provide tick.json, or use --upgrade-existing with --spreadsheet.')
        state = None if args.upgrade_existing else decode_data(args.source.read_bytes())
        if args.dry_run:
            print(f"Valid data: {len(state['nonprofits'])} projects, {len(state['sessions'])} sessions. No data uploaded.")
            return 0
        account = GoogleAccount()
        if args.sign_in: account.sign_in()
        else:
            try: account.access_token()
            except ValueError: account.sign_in()
        api = GoogleSheetsAPI(account)
        store = SheetsStore(api, args.spreadsheet, args.name) if args.spreadsheet else api.create(args.name)
        if args.upgrade_existing:
            state = store.refresh_tables()
            print(f"Upgraded readable tables for {len(state['nonprofits'])} projects and {len(state['sessions'])} sessions; history is unchanged.")
            print("Spreadsheet: https://docs.google.com/spreadsheets/d/" + store.sheet_id + "/edit")
            return 0
        state = migrate(args.source, store)
        print(f"Migrated and verified {len(state['nonprofits'])} projects and {len(state['sessions'])} sessions in Google Sheets ({store.spreadsheet_name}).")
        print("Spreadsheet: https://docs.google.com/spreadsheets/d/" + store.sheet_id + "/edit")
        print("Original tick.json is unchanged. In Tick, sign in with the same Google account and open this spreadsheet.")
        return 0
    except (OSError, ValueError, KeyError, TypeError, EOFError) as error:
        print(f"Migration failed: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Migration interrupted. Keep tick.json; check the destination before retrying.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
