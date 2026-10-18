import unittest
from datetime import date
from night_shift import history_import as imp
from night_shift.models import Mode, HistoryInput
from night_shift.validator import validate_first_trial

class AGapThreeTests(unittest.TestCase):
    def record(self, points):
        grid={p:["휴게"]*14 for p in ("A","1","2","3","4","5","6")}
        for p in grid:
            if p!="A":
                for t in (1,3,4,5)[:points]: grid[p][t]="I1"
        return imp.build_import_record(date(2026,10,16),Mode.FM,grid,{p:p for p in grid},imp.ROSTER)
    def errors(self, r, **kwargs):
        return [e for e in validate_first_trial(r,HistoryInput((),()),**kwargs) if e["rule"]=="8-4-2"]
    def test_three_allowed_four_rejected(self):
        self.assertFalse(self.errors(self.record(3),rules_v220=True))
        self.assertTrue(self.errors(self.record(4),rules_v220=True))
    def test_old_version_keeps_two_point_limit(self):
        self.assertTrue(self.errors(self.record(3),rules_v219=True))
    def test_a_above_general_rejected(self):
        grid={p:["휴게"]*14 for p in ("A","1","2","3","4","5","6")}
        grid["A"][3]="I1"
        r=imp.build_import_record(date(2026,10,16),Mode.FM,grid,{p:p for p in grid},imp.ROSTER)
        self.assertTrue(self.errors(r,rules_v220=True))
