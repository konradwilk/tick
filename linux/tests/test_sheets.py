import copy
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from tick.core import StorageLocation, Tracker, FileStore
from tick.sheets import SheetsStore, GoogleSheetsAPI, decode_log


class FakeAPI:
    def __init__(self):
        self.tables = {}; self.ids = {0: 'TickLog'}
        self.rows = []; self.fail = False; self.title = 'Time is Clearly Kept'; self.after_append = None
    def request(self, method, url, body=None):
        if self.fail: raise ValueError('offline')
        if '?fields=' in url: return {'properties': {'title': self.title}, 'sheets': [{'properties': {'title': title, 'sheetId': key}} for key, title in self.ids.items()]}
        if method == 'GET':
            title = url.split('/values/')[1].split('!')[0]
            return {'values': copy.deepcopy(self.rows if title == 'TickLog' else self.tables[title])}
        if ':batchUpdate' in url:
            self.requests = copy.deepcopy(body['requests'])
            for request in body['requests']:
                if 'addSheet' in request:
                    props = request['addSheet']['properties']; self.ids[props['sheetId']] = props['title']
                if 'updateCells' in request:
                    payload = request['updateCells']; self.tables[self.ids[payload['range']['sheetId']]] = [[next(iter(c['userEnteredValue'].values())) for c in row['values']] for row in payload['rows']]
                if 'appendCells' in request:
                    self.rows.extend([[next(iter(c['userEnteredValue'].values())) for c in row['values']] for row in request['appendCells']['rows']])
                    if self.after_append: self.after_append(self.rows)
            return {}
        if ':append?' in url:
            self.rows.extend(copy.deepcopy(body['values']))
            if self.after_append: self.after_append(self.rows)
            return {}
        raise AssertionError((method, url))


class SheetsTests(unittest.TestCase):
    def test_tracking_restart_stale_save_and_failed_stop(self):
        api = FakeAPI()
        with tempfile.TemporaryDirectory() as folder:
            location = StorageLocation(Path(folder)/'settings.json')
            local = location.select(Path(folder)/'local'); project = local.add_nonprofit('Kitchen 🍲')
            original = local.store.path.read_bytes()
            remote = location.select_sheets(SheetsStore(api,'sheet'), local)
            self.assertEqual(remote.state, local.state)
            self.assertEqual(local.store.path.read_bytes(),original)
            self.assertNotIn('token',location.settings.read_text())
            self.assertNotIn('secret',location.settings.read_text())
            remote.start(project,'Meals')
            stale_store = SheetsStore(api,'sheet'); stale = Tracker(stale_store)
            remote.stop()
            before = copy.deepcopy(stale.state)
            with self.assertRaisesRegex(ValueError,'changed'): stale.update_notes(stale.active['sessionId'],'wrong')
            self.assertEqual(stale.state,before)
            stale.reload(); api.fail = True
            before = copy.deepcopy(stale.state)
            with self.assertRaisesRegex(ValueError,'offline'): stale.add_nonprofit('Other')
            self.assertEqual(stale.state,before)
            api.fail = False
            copied = location.select(Path(folder)/'copy',stale)
            self.assertEqual(location.open().state,copied.state)

    def test_concurrent_branches_preserve_both_versions(self):
        api=FakeAPI(); store=SheetsStore(api,'sheet')
        with tempfile.TemporaryDirectory() as folder:
            tracker=Tracker(FileStore(Path(folder)/'tick.json')); tracker.add_nonprofit('First')
            store.save(tracker.state)
            first = copy.deepcopy(api.rows)
            store.load()
            def race(rows):
                sibling = copy.deepcopy(rows[-1]); sibling[1]='other-revision'; rows.append(sibling)
            api.after_append = race
            with self.assertRaisesRegex(ValueError,'Concurrent'): store.save(tracker.state)
            self.assertEqual(api.rows[:len(first)],first)
            self.assertEqual(len(api.rows),3)
            with self.assertRaisesRegex(ValueError,'Concurrent'): store.load()

    def test_large_unicode_chunks_and_malformed_log(self):
        api=FakeAPI(); store=SheetsStore(api,'sheet')
        with tempfile.TemporaryDirectory() as folder:
            tracker=Tracker(FileStore(Path(folder)/'tick.json')); tracker.add_nonprofit('🍲'*45000)
            store.save(tracker.state)
            self.assertGreater(len(api.rows),1)
            self.assertEqual(store.load(),tracker.state)
            bad=copy.deepcopy(api.rows); bad[-1][3]=999
            with self.assertRaises(ValueError): decode_log(bad)
            with self.assertRaises(ValueError): decode_log(api.rows[:-1])

    def test_migration_preserves_file_active_session_custom_name_and_refuses_overwrite(self):
        spec=importlib.util.spec_from_file_location('migration',Path(__file__).resolve().parents[2]/'tools/migrate_to_sheets.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        api=FakeAPI();store=SheetsStore(api,'sheet','My work hours')
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'tick.json'; tracker=Tracker(FileStore(path)); project=tracker.add_nonprofit('Kitchen 🍲')
            now=datetime(2026,1,1,tzinfo=timezone.utc)
            tracker.start(project,'Meals, cleanup',now);tracker.stop(now+timedelta(minutes=10));tracker.start(project,'Running',now+timedelta(minutes=20))
            original=path.read_bytes()
            state=module.migrate(path,store)
            self.assertEqual(state,store.load());self.assertEqual(path.read_bytes(),original)
            self.assertIsNone(state['sessions'][-1]['endTimeUtc'])
            count=len(api.rows)
            with self.assertRaisesRegex(ValueError,'already contains'): module.migrate(path,SheetsStore(api,'sheet'))
            self.assertEqual(len(api.rows),count)
            self.assertEqual(module.main([str(path),'--dry-run']),0)

    def test_previous_sheet_is_read_without_script(self):
        with tempfile.TemporaryDirectory() as folder:
            tracker=Tracker(FileStore(Path(folder)/'tick.json'));tracker.add_nonprofit('Old')
            class OldAPI(FakeAPI):
                def request(self, method,url,body=None):
                    if '?fields=' in url:return {'properties':{'title':'Old'},'sheets':[{'properties':{'title':'TickData'}}]}
                    return {'values':[['old-revision'],[1],[json.dumps(tracker.state)]]}
            self.assertEqual(SheetsStore(OldAPI(),'sheet').load(),tracker.state)

    def test_unrelated_sheet_is_not_initialized(self):
        class OtherAPI(FakeAPI):
            def request(self,*args):return {'properties':{'title':'Other'},'sheets':[{'properties':{'title':'Business'}}]}
        with self.assertRaisesRegex(ValueError,'no Tick dataset'):SheetsStore(OtherAPI(),'sheet').load()

    def test_readable_rows_totals_upgrade_and_deleted_sessions(self):
        api = FakeAPI(); store = SheetsStore(api, 'sheet')
        with tempfile.TemporaryDirectory() as folder:
            tracker = Tracker(FileStore(Path(folder)/'tick.json'))
            project = tracker.add_nonprofit('Kitchen 🍲')
            now = datetime(2026, 1, 1, tzinfo=timezone.utc)
            tracker.start(project, '=SUM(A1:A9)', now)
            tracker.stop(now + timedelta(minutes=90))
            tracker.start(project, 'Still running', now + timedelta(hours=2))
            store.save(tracker.state)
            self.assertEqual(len(api.tables['Sessions']), 3)
            self.assertEqual(api.tables['Sessions'][1][3:7], ['1:30:00', 1.5, '=SUM(A1:A9)', 'Completed'])
            self.assertEqual(api.tables['Sessions'][2][2:5], ['', '', ''])
            self.assertEqual(api.tables['Projects'][1], ['Kitchen 🍲', 1.5, 2])
            store.verify_tables(tracker.state)
            history = copy.deepcopy(api.rows)
            api.tables['Sessions'] = []
            store.refresh_tables()
            self.assertEqual(api.rows, history)
            self.assertEqual(len(api.tables['Sessions']), 3)
            for request in api.requests:
                if 'updateCells' in request:
                    for row in request['updateCells']['rows']:
                        self.assertTrue(all('formulaValue' not in c['userEnteredValue'] for c in row['values']))
            tracker.state['sessions'] = []
            store.save(tracker.state)
            self.assertEqual(len(api.tables['Sessions']), 1)
            self.assertEqual(api.tables['Projects'][1], ['Kitchen 🍲', 0, 0])
            self.assertTrue(any(r.get('updateSheetProperties', {}).get('properties', {}).get('hidden') for r in api.requests))
