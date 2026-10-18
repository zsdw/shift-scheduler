import unittest
from datetime import date
from types import SimpleNamespace
from night_shift.models import Mode, NightType
from night_shift.service import ShiftRequest, HistorySelection, SolveOptions, run_schedule, calculate_all_stats
from night_shift.balance_notes import balance_reasons
from tests.test_manager_first_last import staff


class VacancyGapTests(unittest.TestCase):
    def test_generated_gap_stage_and_independent_validation(self):
        result = run_schedule(ShiftRequest(date(2026,10,8), NightType.N2, Mode.FLEXIBLE, staff(('3','4'))),
                              HistorySelection(), SolveOptions(rules_version='2.20', seconds=10))
        self.assertTrue(result.valid, result.validation_errors or result.solve_result.status)
        attempts = result.solve_result.attempts
        self.assertTrue(any(a['stage']=='vacancy_manager_fatigue_gap' and a['value'] is not None for a in attempts), attempts)
        stats = calculate_all_stats(result.record)
        notes = balance_reasons(result.record, stats, attempts=attempts)
        self.assertTrue(any('일반근무자 평균' in line and '차이' in line for line in notes))
        for r in result.record.assignments:
            if r.employee_id == 'A' and r.slot.index in (12,13):
                self.assertIn(r.displayed_assignment.label, ('휴게','보안실 대기'))
