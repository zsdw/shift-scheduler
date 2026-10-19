import unittest
from dataclasses import replace
import json
from night_shift.history_store import record_from_json
from night_shift.models import RecordKind
from datetime import datetime
from pathlib import Path
from datetime import date
from night_shift.history_store import actual_record, history_selection
from night_shift.models import HistoryInput
from night_shift.validator import validate_first_trial
from night_shift.solver import solve_first_trial

class LowerStreakTests(unittest.TestCase):
    def setUp(self):
        store=Path(__file__).resolve().parent.parent/'history'
        self.record=replace(record_from_json(json.loads((Path(__file__).parent/'fixtures/patrol_rules_record.json').read_text(encoding='utf-8'))['plan']),kind=RecordKind.ACTUAL,confirmed_at=datetime(2026,10,15))
        # 2026-10-20: 실제 저장소(업로드로 바뀜)에 기대지 않고, 같은 표를 직전 2회 실제 근무로 만들어 1번이 하층 2연속.
        from datetime import timedelta
        day=self.record.context.shift_start_date
        self.past=tuple(replace(self.record,context=replace(self.record.context,shift_start_date=day-timedelta(days=k)))
                        for k in (1,2))
    def errors(self,past,locked=()):
        return [e for e in validate_first_trial(self.record,HistoryInput((),()),rules_v220=True,
                patrol_actuals=past,locked_cells=locked) if e['rule']=='14-9']
    def test_actual_third_lower_is_rejected(self):
        self.assertTrue(any(e['detail'].startswith('1/') for e in self.errors(self.past)))
    def test_only_one_previous_lower_is_allowed(self):
        self.assertFalse(self.errors(self.past[-1:]))
    def test_completed_locked_lower_is_preserved(self):
        locked=tuple((r.employee_id,r.slot.index) for r in self.record.assignments)
        self.assertFalse(self.errors(self.past,locked))
    def test_solver_blocks_third_lower(self):
        result=solve_first_trial(self.record.context,HistoryInput((),()),seconds=20,
                                 rules_v220=True,patrol_actuals=self.past)
        self.assertIsNotNone(result.record,result.status)
        self.assertFalse(any(r.employee_id=='1' and r.actual_post_or_work_type.label=='lower'
                             for r in result.record.assignments))
        self.assertFalse([e for e in validate_first_trial(result.record,HistoryInput((),()),
             rules_v220=True,patrol_actuals=self.past) if e['rule']=='14-9'])
