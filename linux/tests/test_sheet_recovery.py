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
