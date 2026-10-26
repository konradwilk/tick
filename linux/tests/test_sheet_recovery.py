import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from tick.core import Tracker,FileStore

spec=importlib.util.spec_from_file_location('sheet_recovery',Path(__file__).resolve().parents[2]/'tools/recover_sheets.py')
recovery=importlib.util.module_from_spec(spec);spec.loader.exec_module(recovery)

class SheetRecoveryTests(unittest.TestCase):
    def test_sibling_revisions_can_be_exported_independently(self):
        with tempfile.TemporaryDirectory() as folder:
            tracker=Tracker(FileStore(Path(folder)/'tick.json'));tracker.add_nonprofit('Kitchen')
            raw=json.dumps(tracker.state)
            rows=[['tick-log-v1','first','',0,1,raw],['tick-log-v1','left','first',0,1,raw],['tick-log-v1','right','first',0,1,raw]]
            values=recovery.revisions(rows)
            self.assertEqual([r for r,_ in values],['first','left','right'])
            self.assertTrue(all(state==tracker.state for _,state in values))
    def test_corrupt_or_incomplete_revisions_are_rejected(self):
        with self.assertRaises(ValueError):recovery.revisions([['tick-log-v1','bad','',0,2,'{}']])

    def test_row_journal_recovers_sibling_edits_and_deletions(self):
        from test_sheets import FakeAPI
        from tick.sheets import SheetsStore
        fixture=json.loads((Path(__file__).resolve().parents[2]/'fixtures/storage/sheets-rows-v1.json').read_text())
        api=FakeAPI();store=SheetsStore(api,'test');state=fixture['state'];store.save(state)
        state['sessions'][0]['notes']='Left';store.save(state)
        rows=api.tables['TickChanges'];left=json.loads(rows[-1][4]);right=json.loads(rows[-1][4]);right['changes'][0]['row'][-1]=right['changes'][0]['row'][-1].replace('Left','Right')
        sibling=list(rows[-1]);sibling[0]='sibling';sibling[4]=json.dumps(right);rows.append(sibling)
        root=json.loads(api.tables['TickMeta'][0][1]);values=recovery.row_revisions(rows,root)
        self.assertEqual(len(values),3)
        self.assertEqual(values[-2][1]['sessions'][0]['notes'],'Left')
        self.assertEqual(values[-1][1]['sessions'][0]['notes'],'Right')
        rows.pop();state['sessions'].pop();store.save(state)
        self.assertEqual(len(recovery.row_revisions(rows,root)[-1][1]['sessions']),1)
