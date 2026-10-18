import unittest
from datetime import date
from night_shift import history_import as imp
from night_shift.models import Mode,HistoryInput
from night_shift.validator import validate_first_trial
from night_shift.solver import solve_first_trial

class AStandbyCapTests(unittest.TestCase):
    def record(self,count,mode=Mode.FM):
        grid={p:['G1']*14 for p in ('A','1','2','3','4','5','6')}
        grid['A'][:count]=['보안실 대기']*count
        return imp.build_import_record(date(2026,10,22),mode,grid,{p:p for p in grid},imp.ROSTER)
    def errors(self,r,**kw):
        return [e for e in validate_first_trial(r,HistoryInput((),()),rules_v220=True,**kw) if e['rule']=='8-15']
    def test_three_rejected_two_allowed_both_modes(self):
        for mode in (Mode.FM,Mode.FLEXIBLE):
            self.assertTrue(self.errors(self.record(3,mode)))
            self.assertFalse(self.errors(self.record(2,mode)))
    def test_locked_past_preserved_but_no_extra_allowed(self):
        locked=tuple(('A',t) for t in range(3))
        self.assertFalse(self.errors(self.record(3),locked_cells=locked))
        self.assertTrue(self.errors(self.record(4),locked_cells=locked))
    def test_proxy_handover_not_counted_as_actual_a(self):
        self.assertFalse(self.errors(self.record(4),manager_a_end_slot=2))
    def test_actual_generation_respects_cap_and_previous_rules(self):
        for mode in (Mode.FM,Mode.FLEXIBLE):
            result=solve_first_trial(self.record(0,mode).context,HistoryInput((),()),seconds=20,rules_v220=True)
            self.assertIsNotNone(result.record,result.status)
            count=sum(r.employee_id=='A' and r.displayed_assignment.label=='보안실 대기' for r in result.record.assignments)
            self.assertLessEqual(count,2)
            self.assertTrue(any(r.employee_id=='A' and r.displayed_assignment.label=='I1' for r in result.record.assignments))
            self.assertFalse([e for e in validate_first_trial(result.record,HistoryInput((),()),rules_v220=True)
                 if e['rule'] in ('8-15','8-14','12-gap','12-required','12-block')])
