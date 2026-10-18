import unittest
from datetime import date
from night_shift import history_import as imp
from night_shift.models import Mode, HistoryInput
from night_shift.validator import validate_first_trial

class LastThreeRestTests(unittest.TestCase):
    def record(self, ending):
        grid={p:["G1"]*14 for p in ("A","1","2","3","4","5","6")}
        grid["A"][11:14]=["휴게"]*3
        grid["1"][11:14]=ending
        return imp.build_import_record(date(2026,10,9),Mode.FM,grid,{p:p for p in grid},imp.ROSTER)
    def errors(self,r,**kwargs):
        return [e for e in validate_first_trial(r,HistoryInput((),()),rules_v220=True,**kwargs) if e["rule"]=="H-19"]
    def test_three_rest_rejected_a_exempt(self):
        errors=self.errors(self.record(["휴게"]*3))
        self.assertTrue(errors)
        self.assertTrue(all(e["detail"].endswith(": 1") for e in errors))
    def test_two_rest_allowed(self):
        self.assertFalse(self.errors(self.record(["G1","휴게","휴게"])))
    def test_all_locked_preserved_partial_lock_still_checked(self):
        r=self.record(["휴게"]*3)
        self.assertFalse(self.errors(r,locked_cells=(("1",11),("1",12),("1",13))))
        self.assertTrue(self.errors(r,locked_cells=(("1",11),("1",12))))
    def test_proxy_handover_three_rest_allowed(self):
        grid={p:["G1"]*14 for p in ("A","1","2","3","4","5","6")}
        grid["6"][11]="휴게"
        grid["A"][12:14]=["휴게"]*2
        r=imp.build_import_record(date(2026,10,9),Mode.FM,grid,{p:p for p in grid},imp.ROSTER)
        self.assertFalse(self.errors(r,manager_a_end_slot=12))

    def test_junho_general_rejected_proxy_allowed(self):
        from dataclasses import replace
        grid={p:["G1"]*14 for p in ("A","1","2","3","4","5","6")}
        grid["6"][11:14]=["휴게"]*3
        r=imp.build_import_record(date(2026,10,9),Mode.FM,grid,{p:p for p in grid},imp.ROSTER)
        self.assertTrue(self.errors(r))
        r=replace(r,context=replace(r.context,attendance=tuple(
            replace(a,present=False,available_slot_indices=()) if a.employee_id=="A" else
            replace(a,acts_as_manager=True,is_general_worker=False) if a.employee_id=="6" else a
            for a in r.context.attendance)),assignments=tuple(row for row in r.assignments if row.employee_id!="A"))
        self.assertFalse(self.errors(r))
