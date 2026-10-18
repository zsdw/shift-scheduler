import unittest
from datetime import date
from dataclasses import replace
from night_shift.models import Mode, NightType, HistoryInput
from night_shift.service import ShiftRequest, HistorySelection, SolveOptions, run_schedule
from night_shift.validator import validate_first_trial
from tests.test_manager_first_last import staff
from night_shift import history_import as imp


class HolidayEndTests(unittest.TestCase):
    def test_generation_manager_and_proxy(self):
        for proxy, absent, boss in ((False, ('3', '4'), 'A'), (True, ('3',), '6')):
            result = run_schedule(ShiftRequest(date(2026,10,8), NightType.N2, Mode.FM, staff(absent, proxy)),
                                  HistorySelection(), SolveOptions(rules_version='2.20', seconds=20))
            self.assertTrue(result.valid, result.validation_errors or result.solve_result.status)
            end = [r for r in result.record.assignments if r.employee_id == boss and r.slot.index in (12,13)]
            self.assertEqual(len(end),2)
            self.assertTrue(all(r.displayed_assignment.label in ('휴게','보안실 대기') and r.actual_work_time_value == 0 for r in end))

    def test_validator_rejects_post_on_holiday_only_vacancy_two(self):
        grid = {p:['휴게']*14 for p in ('A','1','2','5','6')}
        grid['A'][12] = 'I1'
        record = imp.build_import_record(date(2026,10,8), Mode.FLEXIBLE, grid, {p:p for p in grid}, imp.ROSTER)
        errors = validate_first_trial(record, HistoryInput((), ()), rules_v220=True)
        self.assertTrue(any(e['rule']=='8-12' for e in errors), errors)
        nonholiday = replace(record, context=replace(record.context, shift_start_date=date(2026,10,9)))
        self.assertFalse(any(e['rule']=='8-12' for e in validate_first_trial(nonholiday, HistoryInput((), ()), rules_v220=True)))

