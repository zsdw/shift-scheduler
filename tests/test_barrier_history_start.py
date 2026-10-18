"""차단봉 집계만 10/4부터, 담당 규칙은 10/5부터 적용한다."""
import unittest
from dataclasses import replace
from datetime import date, datetime

import history_ui
from night_shift import history_import as imp
from night_shift.models import Mode, RecordKind, barrier_v2
from night_shift.service import (HistorySelection, ShiftRequest, StaffInput, build_context,
                                duty_rates_from, prepare_engine_inputs)
from night_shift.soft_history import update_soft_debt


def actual(day):
    grid = {p: ['휴게'] * 14 for p in ('A', '1', '2', '3', '4', '5', '6')}
    grid['1'][2] = '보안실 대기'
    grid['1'][1] = grid['1'][3] = 'G1'
    grid['2'][10] = '보안실 대기'
    grid['3'][4] = '상층순찰'
    record = imp.build_import_record(day, Mode.FM, grid, {p: p for p in grid}, imp.ROSTER,
                                     installs=[('1', 2)], removes=[('2', 10)])
    return replace(record, kind=RecordKind.ACTUAL, confirmed_at=datetime(2026, 10, 5))


class BarrierHistoryStartTests(unittest.TestCase):
    def test_average_excludes_old_nights_from_denominator_but_keeps_patrol(self):
        old, current = actual(date(2026, 10, 3)), actual(date(2026, 10, 4))
        rates = duty_rates_from((old, current), ('1', '2', '3'))
        self.assertEqual(rates['barrier'], {'1': 100, '2': 100, '3': 0})
        self.assertEqual(rates['upper']['3'], 100)
        self.assertEqual(duty_rates_from((old,), ('1', '2'))['barrier'], {'1': 0, '2': 0})

    def test_previous_barrier_duties_start_on_october_four(self):
        staff = tuple(StaffInput(p, p, True, p != 'A', int(p) if p != 'A' else None, p == 'A')
                      for p in ('A', '1', '2', '3', '4', '5', '6'))
        context = build_context(ShiftRequest(date(2026, 10, 6), imp.night_type_for(date(2026, 10, 6)), Mode.FM, staff))
        for day, expected in ((date(2026, 10, 3), ()), (date(2026, 10, 4), ('1',))):
            record = actual(day)
            prepared = prepare_engine_inputs(context, HistorySelection(actual_records=(record,)))
            self.assertEqual(prepared.previous_install_ids, expected)
            self.assertEqual(prepared.forbid_install_ids, expected)
            self.assertEqual(prepared.previous_remove_ids, ('2',) if expected else ())
            self.assertEqual(prepared.historical_nights['1'], 1)
            self.assertGreater(prepared.historical_totals['fatigue_value']['1'], 0)

    def test_display_hides_only_old_barrier_tokens(self):
        old = history_ui._duty_tokens(actual(date(2026, 10, 3)))
        new = history_ui._duty_tokens(actual(date(2026, 10, 4)))
        self.assertNotIn('설치', old['1'])
        self.assertNotIn('철수', old['2'])
        self.assertEqual(old['3'], new['3'])
        self.assertIn('설치', new['1'])
        self.assertIn('철수', new['2'])

    def test_old_barriers_do_not_accumulate_soft_debt(self):
        self.assertNotIn('15-7', update_soft_debt(actual(date(2026, 10, 3)), {}))
        self.assertEqual(update_soft_debt(actual(date(2026, 10, 4)), {})['15-7']['1'], 1)

    def test_new_assignment_rule_still_starts_on_october_five(self):
        old = actual(date(2026, 10, 4))
        self.assertFalse(barrier_v2(old.context))
        self.assertTrue(barrier_v2(replace(old.context, shift_start_date=date(2026, 10, 5))))
