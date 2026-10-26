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
        self.tables = {}; self.ids = {0: 'TickLog'}; self.grids = {}
        self.fail = False; self.title = 'Time is Clearly Kept'; self.after_append = None; self.calls=[]
    @property
    def rows(self): return self.tables.setdefault(self.ids.get(0,'TickLog'), [])
    @rows.setter
    def rows(self, value): self.tables[self.ids.get(0,'TickLog')] = value
    def values(self, address):
        import re
        title, _, span = address.partition('!')
        rows = self.tables.get(title, [])
        if not span: return copy.deepcopy(rows)
        m=re.fullmatch(r'([A-Z]+)(\d*)?(?::([A-Z]+)(\d*)?)?',span)
        def column(v):
            n=0
            for c in v:n=n*26+ord(c)-64
            return n-1
        a,b,c,d=m.groups(); start=int(b or 1)-1; end=int(d) if d else (start+1 if not c else len(rows))
        result=[copy.deepcopy(r[column(a):column(c or a)+1]) for r in rows[start:end]]
        while result and not result[-1]:result.pop()
        return result
    def request(self, method, url, body=None):
        from urllib.parse import urlparse, parse_qs,unquote
        self.calls.append((method,url,copy.deepcopy(body)))
        if self.fail: raise ValueError('offline')
        if '?fields=' in url: return {'properties': {'title': self.title}, 'sheets': [{'properties': {'title': title, 'sheetId': key,'gridProperties':self.grids.get(key,{'rowCount':1000,'columnCount':26})}} for key, title in self.ids.items()]}
        if '/values:batchGet?' in url:return {'valueRanges':[{'values':self.values(r)} for r in parse_qs(urlparse(url).query)['ranges']]}
        if method == 'GET':return {'values':self.values(unquote(url.split('/values/')[1].split('?')[0]))}
        if ':batchUpdate' in url:
            self.requests=copy.deepcopy(body['requests'])
            for request in body['requests']:
                if 'addSheet' in request:
                    p=request['addSheet']['properties'];self.ids[p['sheetId']]=p['title'];self.grids[p['sheetId']]=p.get('gridProperties',{})
                if 'updateSheetProperties' in request:
                    p=request['updateSheetProperties']['properties'];identity=p['sheetId']
                    if 'title' in p:
                        old=self.ids[identity];self.ids[identity]=p['title'];self.tables[p['title']]=self.tables.pop(old,[])
                    if 'gridProperties' in p:self.grids.setdefault(identity,{}).update(p['gridProperties'])
                if 'updateCells' in request:
                    p=request['updateCells'];r=p['range'];title=self.ids[r['sheetId']];table=self.tables.setdefault(title,[]);start=r.get('startRowIndex',0)
                    grid=self.grids.get(r['sheetId'],{'rowCount':1000,'columnCount':26})
                    if 'endColumnIndex' in r: assert r['endColumnIndex']<=grid.get('columnCount',26), 'Write exceeds sheet width'
                    if 'endRowIndex' in r: assert r['endRowIndex']<=grid.get('rowCount',1000), 'Write exceeds sheet height'
                    if 'endRowIndex' not in r:table.clear()
                    values=[[next(iter(c['userEnteredValue'].values())) for c in row['values']] for row in p['rows']]
                    while len(table)<start+len(values):table.append([])
                    for i,row in enumerate(values):table[start+i]=row
                if 'appendCells' in request:
                    p=request['appendCells'];target=self.tables.setdefault(self.ids[p['sheetId']],[])
                    target.extend([[next(iter(c['userEnteredValue'].values())) for c in row['values']] for row in p['rows']])
                    if self.after_append:self.after_append(target)
            return {}
        raise AssertionError((method,url))

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
            tracker=Tracker(FileStore(Path(folder)/'tick.json')); project=tracker.add_nonprofit('First')
            store.save(tracker.state)
            first = copy.deepcopy(api.tables['TickChanges'])
            tracker.add_nonprofit('Second')
            def race(rows):
                sibling = copy.deepcopy(rows[-1]); sibling[0]='other-revision'; rows.append(sibling)
            api.after_append = race
            with self.assertRaisesRegex(ValueError,'Concurrent'): store.save(tracker.state)
            self.assertEqual(api.tables['TickChanges'][:len(first)], first)
            self.assertEqual(len(api.tables['TickChanges']), 3)
            with self.assertRaisesRegex(ValueError,'Concurrent'): store.load()

    def test_large_unicode_chunks_and_malformed_log(self):
        api=FakeAPI(); store=SheetsStore(api,'sheet')
        with tempfile.TemporaryDirectory() as folder:
            tracker=Tracker(FileStore(Path(folder)/'tick.json')); tracker.add_nonprofit('🍲'*45000)
            store.save(tracker.state)
            self.assertGreater(len(api.tables['Projects'][1]), 8)
            self.assertEqual(store.load(),tracker.state)
            api.tables['Projects'][1].pop()
            with self.assertRaisesRegex(ValueError, 'Invalid'): store.load()
        with self.assertRaises(ValueError): decode_log([['tick-log-v1','bad','',0,2,'{}']])

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
            self.assertEqual(api.tables['Projects'][1][:3], ['Kitchen 🍲', 1.5, 2])
            store.verify_tables(tracker.state)
            history = copy.deepcopy(api.tables['TickChanges'])
            store.refresh_tables()
            self.assertEqual(api.tables['TickChanges'], history)
            self.assertEqual(len(api.tables['Sessions']), 3)
            for request in api.requests:
                if 'updateCells' in request:
                    for row in request['updateCells']['rows']:
                        self.assertTrue(all('formulaValue' not in c['userEnteredValue'] for c in row['values']))
            tracker.state['sessions'] = []
            store.save(tracker.state)
            self.assertEqual(len(api.tables['Sessions']), 3)
            self.assertTrue(all(r[10]=='1' for r in api.tables['Sessions'][1:]))
            self.assertEqual(api.tables['Projects'][1][:3], ['Kitchen 🍲', 0, 0])
            self.assertEqual(store.load()['sessions'], [])

    def test_migrates_legacy_log_once_and_keeps_backup(self):
        api=FakeAPI(); store=SheetsStore(api,'sheet')
        with tempfile.TemporaryDirectory() as folder:
            tracker=Tracker(FileStore(Path(folder)/'tick.json'));project=tracker.add_nonprofit('Old')
            raw=json.dumps(tracker.state)
            api.rows=[['tick-log-v1','old','',0,1,raw]]
            self.assertEqual(store.load(),tracker.state)
            store.save(tracker.state)
            self.assertEqual(api.tables['TickLogBackup'], [['tick-log-v1','old','',0,1,raw]])
            self.assertNotIn('TickLog',api.ids.values())
            api.calls=[]; tracker.add_nonprofit('New');store.save(tracker.state)
            self.assertEqual(len(api.calls),3)
            self.assertFalse(any('TickLog' in url for _,url,_ in api.calls))
            self.assertFalse(any('repeatCell' in r or 'updateDimensionProperties' in r for r in api.requests))

    def test_only_edited_row_is_written_and_row_sorting_is_safe(self):
        api=FakeAPI(); store=SheetsStore(api,'sheet')
        with tempfile.TemporaryDirectory() as folder:
            tracker=Tracker(FileStore(Path(folder)/'tick.json'));project=tracker.add_nonprofit('Kitchen')
            now=datetime(2026,1,1,tzinfo=timezone.utc)
            for i in range(3):tracker.add_session(project,'Notes',now+timedelta(hours=i*2),now+timedelta(hours=i*2+1))
            store.save(tracker.state)
            api.tables['Sessions'][1:]=reversed(api.tables['Sessions'][1:])
            identity=tracker.state['sessions'][0]['sessionId']
            tracker.update_notes(identity,'Changed');api.calls=[];store.save(tracker.state)
            self.assertEqual(len(api.calls),3)
            updates=[r['updateCells'] for r in api.requests if 'updateCells' in r]
            self.assertEqual(len(updates),1)
            self.assertEqual(updates[0]['range']['startRowIndex'],3)
            self.assertEqual(api.tables['Sessions'][3][5],'Changed')
            # A no-op makes no write and adds no journal entry.
            before=copy.deepcopy(api.tables['TickChanges']);store.save(tracker.state)
            self.assertEqual(before,api.tables['TickChanges'])

    def test_shortening_long_note_clears_old_chunks(self):
        api=FakeAPI();store=SheetsStore(api,'sheet')
        with tempfile.TemporaryDirectory() as folder:
            tracker=Tracker(FileStore(Path(folder)/'tick.json'));project=tracker.add_nonprofit('Kitchen')
            now=datetime(2026,1,1,tzinfo=timezone.utc)
            tracker.add_session(project,'🍲'*45000,now,now+timedelta(hours=1));store.save(tracker.state)
            width=len(api.tables['Sessions'][1]);tracker.update_notes(tracker.state['sessions'][0]['sessionId'],'Short');store.save(tracker.state)
            update=next(r['updateCells'] for r in api.requests if 'updateCells' in r)
            self.assertEqual(update['range']['endColumnIndex'],width)
            self.assertLess(len(update['rows'][0]['values']),width)
            self.assertEqual(store.load()['sessions'][0]['notes'],'Short')

    def test_duplicate_id_and_missing_header_are_rejected(self):
        api=FakeAPI();store=SheetsStore(api,'sheet')
        with tempfile.TemporaryDirectory() as folder:
            tracker=Tracker(FileStore(Path(folder)/'tick.json'));tracker.add_nonprofit('Kitchen');store.save(tracker.state)
            api.tables['Projects'].append(copy.deepcopy(api.tables['Projects'][1]))
            with self.assertRaisesRegex(ValueError,'duplicate'):store.load()
            api.tables['Projects'].pop();api.tables['Sessions']=[]
            with self.assertRaisesRegex(ValueError,'headers'):store.load()

    def test_wide_row_grid_growth_precedes_writes_and_long_noop_is_free(self):
        fixture=json.loads((Path(__file__).resolve().parents[2]/'fixtures/storage/sheets-rows-v1.json').read_text())
        state=fixture['state'];state['sessions'][0]['notes']='A'*350000
        api=FakeAPI();store=SheetsStore(api,'sheet');store.save(state)
        writes=[(i,r['updateCells']) for i,r in enumerate(api.requests) if 'updateCells'in r]
        wide=next((i,r) for i,r in writes if r['range']['endColumnIndex']>26)
        self.assertTrue(any(i<wide[0] and r.get('updateSheetProperties',{}).get('properties',{}).get('gridProperties',{}).get('columnCount',0)>26 for i,r in enumerate(api.requests)))
        history=copy.deepcopy(api.tables['TickChanges']);store.save(state)
        self.assertEqual(history,api.tables['TickChanges'])

    def test_migration_from_narrow_generated_tables_and_missing_journal(self):
        fixture=json.loads((Path(__file__).resolve().parents[2]/'fixtures/storage/sheets-rows-v1.json').read_text())
        api=FakeAPI();api.ids.update({174001:'Sessions',174002:'Projects'});api.grids.update({174001:{'rowCount':1000,'columnCount':8},174002:{'rowCount':1000,'columnCount':3}})
        raw=json.dumps(fixture['state']);api.rows=[['tick-log-v1','old','',0,1,raw]]
        store=SheetsStore(api,'sheet');store.load();store.save(fixture['state'])
        for request in api.requests:
            dimension=request.get('updateDimensionProperties',{}).get('range')
            if dimension:self.assertGreater(dimension['endIndex'],dimension['startIndex'])
        api.tables['TickChanges']=[]
        with self.assertRaisesRegex(ValueError,'journal is missing'):store.load()
