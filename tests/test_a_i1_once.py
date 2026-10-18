import unittest
from datetime import date
from dataclasses import replace
from night_shift import history_import as imp
from night_shift.models import Mode,HistoryInput
from night_shift.validator import validate_first_trial
from night_shift.solver import solve_first_trial

class AI1OnceTests(unittest.TestCase):
    def record(self,slot=None,mode=Mode.FM):
        grid={p:['G1']*14 for p in ('A','1','2','3','4','5','6')}
        if slot is not None:grid['A'][slot]='I1'
        return imp.build_import_record(date(2026,10,22),mode,grid,{p:p for p in grid},imp.ROSTER)
    def errors(self,r,**kw):
        return [e for e in validate_first_trial(r,HistoryInput((),()),rules_v220=True,**kw) if e['rule']=='8-14']
    def test_missing_i1_rejected_both_modes(self):
        for mode in (Mode.FM,Mode.FLEXIBLE):self.assertTrue(self.errors(self.record(mode=mode)))
    def test_i1_on_other_hour_allowed_and_04_still_forbidden(self):
        self.assertFalse(self.errors(self.record(8)))
        errors=validate_first_trial(self.record(10),HistoryInput((),()),rules_v220=True)
        self.assertTrue(any(e['rule']=='8-10' for e in errors))
    def test_absent_and_entirely_locked_a_preserved(self):
        r=self.record()
        self.assertFalse(self.errors(r,locked_cells=tuple(('A',t) for t in range(14))))
        r=replace(r,context=replace(r.context,attendance=tuple(replace(a,present=False,available_slot_indices=None)
             if a.employee_id=='A' else a for a in r.context.attendance)))
        self.assertFalse(self.errors(r))
    def test_actual_generation_both_modes(self):
        for mode in (Mode.FM,Mode.FLEXIBLE):
            result=solve_first_trial(self.record(mode=mode).context,HistoryInput((),()),seconds=20,rules_v220=True)
            self.assertIsNotNone(result.record,result.status)
            self.assertTrue(any(r.employee_id=='A' and r.displayed_assignment.label=='I1' and r.slot.index!=10
                                for r in result.record.assignments))
            self.assertFalse([e for e in validate_first_trial(result.record,HistoryInput((),()),rules_v220=True)
                              if e['rule'] in ('8-14','8-10','12-gap','12-required','12-block')])
