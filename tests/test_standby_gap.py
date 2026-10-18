import unittest
from datetime import date
from dataclasses import replace
from night_shift import history_import as imp
from night_shift.models import Mode,HistoryInput
from night_shift.validator import validate_first_trial
from night_shift.solver import solve_first_trial

class StandbyGapTests(unittest.TestCase):
    def record(self,counts=None,mode=Mode.FM):
        grid={p:['G1']*14 for p in ('A','1','2','3','4','5','6')}
        for p,n in (counts or {}).items():grid[p][:n]=['보안실 대기']*n
        return imp.build_import_record(date(2026,10,22),mode,grid,{p:p for p in grid},imp.ROSTER)
    def errors(self,r):
        return [e for e in validate_first_trial(r,HistoryInput((),()),rules_v220=True) if e['rule']=='12-gap']
    def test_two_difference_rejected_including_zero(self):
        self.assertTrue(self.errors(self.record({'1':2})))
        self.assertTrue(self.errors(self.record({'1':3,'2':1,'3':1,'4':1,'5':1,'6':1})))
    def test_one_difference_allowed_and_control_a_excluded(self):
        self.assertFalse(self.errors(self.record({'A':5,'1':1})))
        self.assertFalse(self.errors(self.record({'A':6})))
    def test_partial_worker_included(self):
        r=self.record({'1':2})
        r=replace(r,context=replace(r.context,attendance=tuple(replace(a,available_slot_indices=tuple(range(7)))
             if a.employee_id=='6' else a for a in r.context.attendance)))
        self.assertTrue(self.errors(r))
    def test_actual_generation_balances_all_and_keeps_required_standby(self):
        for mode in (Mode.FM,Mode.FLEXIBLE):
            result=solve_first_trial(self.record(mode=mode).context,HistoryInput((),()),seconds=20,rules_v220=True)
            self.assertIsNotNone(result.record,result.status)
            counts={p:sum(r.employee_id==p and r.displayed_assignment.label=='보안실 대기'
                     for r in result.record.assignments) for p in ('1','2','3','4','5','6')}
            self.assertLessEqual(max(counts.values())-min(counts.values()),1)
            errors=validate_first_trial(result.record,HistoryInput((),()),rules_v220=True)
            self.assertFalse([e for e in errors if e['rule'] in ('12-gap','12-required','12-block','12-third','12-protected')])
