import unittest
from datetime import date
from dataclasses import replace
from night_shift import history_import as imp
from night_shift.models import Mode,HistoryInput
from night_shift.validator import validate_first_trial
from night_shift.solver import solve_first_trial

class ThirdStandbyTests(unittest.TestCase):
    def record(self,third='휴게',mode=Mode.FM):
        grid={p:['G1']*14 for p in ('A','1','2','3','4','5','6')}
        grid['1'][3]='상층순찰'
        grid['1'][4:7]=['휴게','휴게',third]
        return imp.build_import_record(date(2026,10,21),mode,grid,{p:p for p in grid},imp.ROSTER)
    def errors(self,r,**kw):
        return [e for e in validate_first_trial(r,HistoryInput((),()),rules_v220=True,**kw) if e['rule']=='12-third']
    def test_third_rest_rejected_but_standby_allowed(self):
        for mode in (Mode.FM,Mode.FLEXIBLE):
            self.assertTrue(self.errors(self.record(mode=mode)))
            self.assertFalse(self.errors(self.record('보안실 대기',mode)))
    def test_first_two_plain_rest_cells_cannot_be_standby(self):
        from night_shift.profiles import make_record
        r=self.record('보안실 대기',Mode.FLEXIBLE)
        wrong=replace(r,assignments=tuple(make_record(r.context,'1',4,'보안실 대기')
            if a.employee_id=='1' and a.slot.index==4 else a for a in r.assignments))
        errors=validate_first_trial(wrong,HistoryInput((),()),rules_v220=True)
        self.assertTrue(any(e['rule']=='12-protected' for e in errors))
    def test_actual_post_and_locked_history_preserved(self):
        self.assertFalse(self.errors(self.record('I1',Mode.FLEXIBLE)))
        self.assertFalse(self.errors(self.record(),locked_cells=(('1',6),)))
    def test_solver_and_standby_pair_objective(self):
        result=solve_first_trial(self.record().context,HistoryInput((),()),seconds=20,rules_v220=True)
        self.assertIsNotNone(result.record,result.status)
        self.assertFalse(self.errors(result.record))
        self.assertTrue(any(a['stage']=='avoid_consecutive_standby' for a in result.attempts))
        for p in ('A','1','2','3','4','5','6'):
            rows=sorted((r for r in result.record.assignments if r.employee_id==p),key=lambda r:r.slot.index)
            for t in range(11):
                if rows[t].actual_post_or_work_type.kind.value=='patrol':
                    if all(rows[j].actual_rest_time_value==1 for j in (t+1,t+2,t+3)):
                        if rows[t+3].displayed_assignment.label in ('휴게','보안실 대기'):
                            self.assertEqual(rows[t+3].displayed_assignment.label,'보안실 대기')
