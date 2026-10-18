import unittest
from dataclasses import replace
from datetime import date
from night_shift import history_import as imp
from night_shift.models import Mode,HistoryInput
from night_shift.validator import validate_first_trial
from night_shift.solver import solve_first_trial

class SouthPairTests(unittest.TestCase):
    def record(self, day=date(2026,10,21),mode=Mode.FM):
        grid={p:['휴게']*14 for p in ('A','1','2','3','4','5','6')}
        grid['1'][12]='G2';grid['1'][13]='G3'
        return imp.build_import_record(day,mode,grid,{p:p for p in grid},imp.ROSTER)
    def errors(self,r,**kw):
        return [e for e in validate_first_trial(r,HistoryInput((),()),rules_v220=True,**kw) if e['rule']=='5-3-1']
    def test_weekday_rejects_cross_south_labels_both_modes(self):
        for mode in (Mode.FM,Mode.FLEXIBLE):self.assertTrue(self.errors(self.record(mode=mode)))
    def test_next_holiday_exempt(self):
        for d in (date(2026,10,16),date(2026,10,8)):
            self.assertFalse(self.errors(self.record(d)))
    def test_one_and_two_absences_not_exempt(self):
        # 2026-10-18 사용자 확정: 결원 2명 구간 예외 삭제 → 결원 1·2명 모두 금지
        r=self.record()
        for absent in (('5',),('5','6')):
            changed=replace(r,context=replace(r.context,attendance=tuple(
                replace(a,present=False,available_slot_indices=None) if a.employee_id in absent else a for a in r.context.attendance)),
                assignments=tuple(a for a in r.assignments if a.employee_id not in absent))
            self.assertTrue(self.errors(changed))
    def test_midshift_two_vacancies_not_exempt(self):
        # 긴급 이탈 등으로 결원 2명이 된 시간도 적용 (2026-10-18 사용자 확정)
        r=self.record()
        # partial_vacancy_profile: 없으면 §0-4-1에서 먼저 멈춰 5-3-1까지 가지 않는다(종전 '예외' 검사는 그래서 늘 통과했음)
        changed=replace(r,context=replace(r.context,partial_vacancy_profile=True,attendance=tuple(
            replace(a,available_slot_indices=tuple(range(7))) if a.employee_id in ('5','6') else a
            for a in r.context.attendance)))
        self.assertTrue(self.errors(changed))
    def test_emergency_manager_leave_morning_south_not_paired(self):
        # 사용자 사례(10/18): 결원 1 + 23시 통제A 긴급 반차(01시 퇴근) → 06·07시 결원 2명이어도 남문 2시간 연속 없음
        from tests.test_manager_late_half import request
        from night_shift.service import HistorySelection, SolveOptions, run_schedule, run_reoptimization
        o=SolveOptions(rules_version="2.20",seconds=20,prefer_dual_mode=False)
        base=run_schedule(request(absent=("4",)),HistorySelection(),o)
        out=run_reoptimization(base,5,"A",7,HistorySelection(),o,"후반부 반차 (01시 퇴근)")
        self.assertTrue(out.valid,(out.solve_result.status,out.validation_errors))
        for p in ('A','1','2','3','5','6'):
            slots={a.slot.index for a in out.record.assignments if a.employee_id==p
                   and a.displayed_assignment.label in ('G2','G3','G2(1)')}
            self.assertFalse(any(t+1 in slots for t in slots),(p,sorted(slots)))
    def test_same_south_post_rejected_and_sunday_start_included(self):
        r=self.record(date(2026,10,18))
        from night_shift.models import Assignment
        changed=replace(r,assignments=tuple(replace(a,displayed_assignment=Assignment(a.displayed_assignment.kind,'G2'))
            if a.employee_id=='1' and a.slot.index==13 else a for a in r.assignments))
        self.assertTrue(self.errors(changed))
    def test_only_fully_locked_pair_preserved(self):
        r=self.record()
        self.assertFalse(self.errors(r,locked_cells=(('1',12),('1',13))))
        self.assertTrue(self.errors(r,locked_cells=(('1',12),)))
    def test_solver_generates_without_south_pairs(self):
        r=self.record()
        result=solve_first_trial(r.context,HistoryInput((),()),seconds=20,rules_v220=True)
        self.assertIsNotNone(result.record,result.status)
        for p in ('A','1','2','3','4','5','6'):
            slots={a.slot.index for a in result.record.assignments if a.employee_id==p
                   and a.displayed_assignment.label in ('G2','G3','G2(1)')}
            self.assertFalse(any(t+1 in slots for t in slots))
        self.assertFalse(self.errors(result.record))
