import unittest
import json
from night_shift.history_store import record_from_json
from night_shift.models import RecordKind
from datetime import datetime
from dataclasses import replace
from datetime import date
from pathlib import Path
from night_shift.history_store import actual_record
from night_shift.models import HistoryInput
from night_shift.validator import validate_first_trial
from night_shift.solver import solve_first_trial

class PatrolTwoTests(unittest.TestCase):
    def setUp(self):
        self.current=replace(record_from_json(json.loads((Path(__file__).parent/'fixtures/patrol_rules_record.json').read_text(encoding='utf-8'))['plan']),kind=RecordKind.ACTUAL,confirmed_at=datetime(2026,10,15))
        self.excluded=replace(self.current,context=replace(self.current.context,shift_start_date=date(2026,10,15)))
        self.patrolled=replace(self.current,context=replace(self.current.context,shift_start_date=date(2026,10,16)),
            assignments=tuple(replace(r,employee_id='2') if r.employee_id=='3' and r.actual_post_or_work_type.kind.value=='patrol' else r for r in self.current.assignments))
    def errors(self,past):
        return [e for e in validate_first_trial(self.current,HistoryInput((),()),rules_v220=True,
                patrol_actuals=past) if e['rule']=='14-1-2']
    def test_first_and_second_attendance_are_protected(self):
        self.assertTrue(self.errors((self.excluded,)))
        self.assertTrue(self.errors((self.excluded,self.patrolled)))
    def test_protection_expires_after_two_attendances(self):
        third=replace(self.patrolled,context=replace(self.patrolled.context,shift_start_date=date(2026,10,17)))
        self.assertFalse(self.errors((self.excluded,self.patrolled,third)))
    def test_absence_does_not_consume_protection(self):
        absent=replace(self.patrolled,context=replace(self.patrolled.context,attendance=tuple(
            replace(a,present=False) if a.employee_id=='2' else a for a in self.patrolled.context.attendance)))
        self.assertTrue(self.errors((self.excluded,absent,self.patrolled)))
    def test_solver_assigns_patrol_in_second_attendance(self):
        result=solve_first_trial(self.current.context,HistoryInput((),()),seconds=20,rules_v220=True,
                                 patrol_actuals=(self.excluded,self.patrolled))
        self.assertIsNotNone(result.record,result.status)
        self.assertTrue(any(r.employee_id=='2' and r.actual_post_or_work_type.kind.value=='patrol'
                            for r in result.record.assignments))
        self.assertFalse([e for e in validate_first_trial(result.record,HistoryInput((),()),rules_v220=True,
             patrol_actuals=(self.excluded,self.patrolled)) if e['rule']=='14-1-2'])
