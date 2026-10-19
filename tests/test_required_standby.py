import unittest
from datetime import date
from dataclasses import replace
from night_shift import history_import as imp
from night_shift.models import Mode,HistoryInput
from night_shift.validator import validate_first_trial
from night_shift.solver import solve_first_trial

class RequiredStandbyTests(unittest.TestCase):
    def record(self,mode=Mode.FM):
        grid={p:['G1']*14 for p in ('A','1','2','3','4','5','6')}
        return imp.build_import_record(date(2026,10,22),mode,grid,{p:p for p in grid},imp.ROSTER)
    def errors(self,r,**kwargs):
        return [e for e in validate_first_trial(r,HistoryInput((),()),rules_v220=True,**kwargs) if e['rule']=='12-required']
    def test_every_hour_until_05_required_both_modes(self):
        for mode in (Mode.FM,Mode.FLEXIBLE):
            errors=self.errors(self.record(mode))
            self.assertEqual({int(e['detail'].split(':')[0]) for e in errors},set(range(12)))
    def test_two_absences_and_midshift_absences_exempt(self):
        r=self.record()
        for start in (0,7):
            att=tuple(replace(a,present=start!=0,available_slot_indices=tuple(range(start)) if start else None)
                      if a.employee_id in ('5','6') else a for a in r.context.attendance)
            changed=replace(r,context=replace(r.context,attendance=att,
                partial_vacancy_profile=start>0,effective_mode=Mode.FLEXIBLE))
            all_errors=validate_first_trial(changed,HistoryInput((),()),rules_v220=True)
            self.assertFalse(any(e["rule"] in ("scope","§0-4-1") for e in all_errors),all_errors)
            self.assertEqual(len(self.errors(changed)),start)
    def test_one_absence_still_requires_every_hour(self):
        r=self.record()
        changed=replace(r,context=replace(r.context,attendance=tuple(
            replace(a,present=False,available_slot_indices=None) if a.employee_id=='6' else a
            for a in r.context.attendance)),assignments=tuple(a for a in r.assignments if a.employee_id!='6'))
        # 2026-10-18 사용자 확정: 결원 1명 시간의 대기자 최소 1명은 '가능하면 지킬 규칙'(Solver 소프트 맨 앞)이라
        # Validator 하드 검사 대상이 아니다(종전 기대값 12는 하드 시절).
        self.assertEqual(len(self.errors(changed)),0)
    def test_whole_locked_column_preserved(self):
        r=self.record()
        errors=self.errors(r,locked_cells=tuple((a.employee_id,7) for a in r.context.attendance))
        self.assertEqual(len(errors),11)
    def test_actual_generation_has_standby_all_12_hours(self):
        for mode in (Mode.FM,Mode.FLEXIBLE):
            solved=solve_first_trial(self.record(mode).context,HistoryInput((),()),seconds=20,rules_v220=True)
            self.assertIsNotNone(solved.record,solved.status)
            self.assertFalse(self.errors(solved.record))
            self.assertEqual({r.slot.index for r in solved.record.assignments if r.displayed_assignment.label=='보안실 대기'} & set(range(12)),set(range(12)))
