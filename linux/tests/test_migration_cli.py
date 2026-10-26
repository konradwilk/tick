"""Run the real CLI path with fake Google sign-in and a real direct-API store."""
import copy
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tick.core import FileStore,Tracker
from tick.sheets import GoogleSheetsAPI

spec=importlib.util.spec_from_file_location('migration_cli',Path(__file__).resolve().parents[2]/'tools/migrate_to_sheets.py')
migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)

class Account:
    def __init__(self):self.signed_in=False;self.sign_ins=0
    def access_token(self):
        if not self.signed_in:raise ValueError('Sign in required')
        return 'fake-token'
    def sign_in(self):self.signed_in=True;self.sign_ins+=1;return self

class MigrationCLITests(unittest.TestCase):
    def test_new_browser_flow_default_and_custom_name(self):
        for custom in (None,'My work hours'):
            with self.subTest(name=custom), tempfile.TemporaryDirectory() as folder:
                path=Path(folder)/'tick.json';tracker=Tracker(FileStore(path));tracker.add_nonprofit('Kitchen 🍲');original=path.read_bytes()
                from test_sheets import FakeAPI
                account=Account();created=[];remote=FakeAPI()
                def request(method,url,body=None):
                    if method=='POST' and url.endswith('/spreadsheets'):
                        created.append(body['properties']['title']);remote.title=created[0];return {'spreadsheetId':'new-sheet'}
                    return remote.request(method,url,body)
                api=GoogleSheetsAPI(account)
                argv=[str(path)]+(['--name',custom] if custom else [])
                output=io.StringIO()
                with patch.object(migration,'GoogleAccount',return_value=account),patch.object(migration,'GoogleSheetsAPI',return_value=api),patch.object(api,'request',side_effect=request),patch('sys.stdout',output):
                    self.assertEqual(migration.main(argv),0)
                self.assertEqual(created,[custom or 'Time is Clearly Kept']);self.assertEqual(account.sign_ins,1)
                self.assertEqual(path.read_bytes(),original)
                self.assertIn('Migrated and verified',output.getvalue());self.assertIn('new-sheet/edit',output.getvalue())
                from tick.sheets import SheetsStore
                self.assertEqual(SheetsStore(remote,'new-sheet').load(),tracker.state)

    def test_dry_run_and_invalid_source_never_sign_in(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'tick.json';tracker=Tracker(FileStore(path));tracker.add_nonprofit('Kitchen')
            with patch.object(migration,'GoogleAccount') as account,patch('sys.stdout',io.StringIO()):
                self.assertEqual(migration.main([str(path),'--dry-run']),0);account.assert_not_called()
            path.write_text('invalid')
            with patch.object(migration,'GoogleAccount') as account,patch('sys.stderr',io.StringIO()):
                self.assertEqual(migration.main([str(path)]),1);account.assert_not_called()

    def test_upgrade_existing_needs_no_source_and_keeps_history(self):
        from test_sheets import FakeAPI
        from tick.sheets import SheetsStore
        with tempfile.TemporaryDirectory() as folder:
            tracker=Tracker(FileStore(Path(folder)/'tick.json'));tracker.add_nonprofit('Kitchen')
            api=FakeAPI();SheetsStore(api,'existing').save(tracker.state)
            history=copy.deepcopy(api.tables['TickChanges'])
            account=Account();account.signed_in=True
            with patch.object(migration,'GoogleAccount',return_value=account),patch.object(migration,'GoogleSheetsAPI',return_value=api),patch('sys.stdout',io.StringIO()) as output:
                self.assertEqual(migration.main(['--upgrade-existing','--spreadsheet','existing']),0)
            self.assertEqual(api.tables['TickChanges'],history)
            self.assertEqual(api.tables['Projects'][1][:3],['Kitchen',0,0])
            self.assertIn('history is unchanged',output.getvalue())

    def test_invalid_upgrade_arguments_never_sign_in(self):
        for argv in ([],['--upgrade-existing'],['--upgrade-existing','--spreadsheet','sheet','--dry-run'],['source.json','--upgrade-existing','--spreadsheet','sheet']):
            with self.subTest(args=argv),patch.object(migration,'GoogleAccount') as account,patch('sys.stderr',io.StringIO()):
                self.assertEqual(migration.main(argv),1);account.assert_not_called()

    def test_upgrade_legacy_spreadsheet_preserves_backup_and_is_repeatable(self):
        from test_sheets import FakeAPI
        from tick.sheets import SheetsStore
        fixture=json.loads((Path(__file__).resolve().parents[2]/'fixtures/storage/sheets-rows-v1.json').read_text())
        state=fixture['state'];api=FakeAPI();api.title='Existing work hours'
        original=[['tick-log-v1','legacy','',0,1,json.dumps(state)]]
        api.rows=copy.deepcopy(original)
        account=Account();account.signed_in=True
        args=['--upgrade-existing','--spreadsheet','https://docs.google.com/spreadsheets/d/existing/edit']
        with patch.object(migration,'GoogleAccount',return_value=account),patch.object(migration,'GoogleSheetsAPI',return_value=api),patch('sys.stdout',io.StringIO()) as output:
            self.assertEqual(migration.main(args),0)
            self.assertIn('Upgraded and verified row storage',output.getvalue())
            self.assertIn('existing/edit',output.getvalue())
            changes=copy.deepcopy(api.tables['TickChanges'])
            self.assertEqual(migration.main(args),0)
        self.assertEqual(api.tables['TickLogBackup'],original)
        self.assertEqual(api.tables['TickChanges'],changes)
        self.assertEqual(SheetsStore(api,'existing').load(),state)
        self.assertEqual(api.title,'Existing work hours')
