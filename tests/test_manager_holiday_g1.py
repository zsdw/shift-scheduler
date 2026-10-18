import unittest
from datetime import date
from dataclasses import replace
from night_shift import history_import as imp
from night_shift.models import Mode, HistoryInput
from night_shift.validator import validate_first_trial

class HolidayG1Tests(unittest.TestCase):
    def record(self, day, mode=Mode.FM):
        grid={p:["휴게"]*14 for p in ("A","1","2","3","4","5","6")}
        grid["A"][12]="G1"
        return imp.build_import_record(day,mode,grid,{p:p for p in grid},imp.ROSTER)

    def errors(self, record, **kwargs):
        return [e for e in validate_first_trial(record,HistoryInput((),()),rules_v220=True,**kwargs) if e["rule"]=="8-13"]

    def test_holiday_g1_rejected_both_modes(self):
        for mode in (Mode.FM,Mode.FLEXIBLE):
            self.assertTrue(self.errors(self.record(date(2026,10,8),mode)))

    def test_weekend_included(self):
        for day in (date(2026,10,16), date(2026,10,17)):
            for mode in (Mode.FM, Mode.FLEXIBLE):
                self.assertTrue(self.errors(self.record(day,mode)))

    def test_normal_weekday_excluded(self):
        self.assertFalse(self.errors(self.record(date(2026,10,13))))

    def test_locked_g1_preserved_future_still_checked(self):
        r=self.record(date(2026,10,8))
        self.assertFalse(self.errors(r,reoptimization=True,locked_cells=(("A",12),)))
        self.assertTrue(self.errors(r,reoptimization=True,locked_cells=(("A",11),)))

    def test_other_post_allowed_by_this_rule(self):
        grid={p:["휴게"]*14 for p in ("A","1","2","3","4","5","6")}
        grid["A"][12]="I1"
        r=imp.build_import_record(date(2026,10,8),Mode.FM,grid,{p:p for p in grid},imp.ROSTER)
        self.assertFalse(self.errors(r))

    def test_proxy_handover_included(self):
        # 2026-10-13 사용자 확정: 준호 관리자 대행도 포함 — 중도 인계 뒤 관리자 줄(A)을 준호가 서도 06시 G1 금지
        self.assertTrue(self.errors(self.record(date(2026,10,8)), manager_a_end_slot=12))

    def test_full_day_proxy_included(self):
        # A 결근·준호(6) 하루 대행: 준호 06시 G1이면 위반
        grid={p:["휴게"]*14 for p in ("A","1","2","3","4","5","6")}
        grid["6"][12]="G1"
        r=imp.build_import_record(date(2026,10,8),Mode.FM,grid,{p:p for p in grid},imp.ROSTER)
        att=tuple(replace(a,present=False,acts_as_manager=False,available_slot_indices=None) if a.employee_id=="A"
                  else replace(a,acts_as_manager=True,is_general_worker=False) if a.employee_id=="6" else a for a in r.context.attendance)
        r=replace(r,context=replace(r.context,attendance=att),
                  assignments=tuple(a for a in r.assignments if a.employee_id!="A"))
        self.assertTrue(self.errors(r))
        grid["6"][12]="I1"
        ok=imp.build_import_record(date(2026,10,8),Mode.FM,grid,{p:p for p in grid},imp.ROSTER)
        ok=replace(ok,context=replace(ok.context,attendance=att),assignments=tuple(a for a in ok.assignments if a.employee_id!="A"))
        self.assertFalse(self.errors(ok))
