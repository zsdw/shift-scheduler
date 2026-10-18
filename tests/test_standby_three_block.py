import unittest
from datetime import date
from night_shift import history_import as imp
from night_shift.models import Mode,HistoryInput
from night_shift.validator import validate_first_trial
from night_shift.solver import solve_first_trial

class StandbyBlockTests(unittest.TestCase):
    def record(self,block):
        grid={p:['G1']*14 for p in ('A','1','2','3','4','5','6')}
        grid['1'][6:9]=block
        return imp.build_import_record(date(2026,10,21),Mode.FM,grid,{p:p for p in grid},imp.ROSTER)
    def errors(self,block,**kw):
        return [e for e in validate_first_trial(self.record(block),HistoryInput((),()),rules_v220=True,**kw) if e['rule']=='12-block']
    def test_bad_sequences_rejected(self):
        for block in (['보안실 대기']*3,['휴게','보안실 대기','휴게'],['휴게','보안실 대기','보안실 대기']):
            self.assertTrue(self.errors(block),block)
    def test_two_adjacent_rests_and_locked_history_allowed(self):
        for block in (['휴게','휴게','보안실 대기'],['보안실 대기','휴게','휴게'],['휴게']*3):
            self.assertFalse(self.errors(block),block)
        self.assertFalse(self.errors(['보안실 대기']*3,locked_cells=tuple(('1',t) for t in (6,7,8))))
    def test_actual_solver_and_whole_night_load_objective(self):
        solved=solve_first_trial(self.record(['휴게']*3).context,HistoryInput((),()),seconds=20,rules_v220=True)
        self.assertIsNotNone(solved.record,solved.status)
        errors=validate_first_trial(solved.record,HistoryInput((),()),rules_v220=True)
        self.assertFalse([e for e in errors if e['rule']=='12-block'])
        self.assertTrue(any(a['stage']=='standby_total_load' for a in solved.attempts))
