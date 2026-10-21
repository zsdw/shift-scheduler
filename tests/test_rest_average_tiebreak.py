"""휴게 순번 동점은 최근 6근무 평균 피로도 높은 사람 우선 (2026-10-22 사용자 확정, 종전 낮은 사람)."""
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from dataclasses import replace
from datetime import date
from fractions import Fraction

from night_shift.soft_history import recent_six_fatigue_averages, rest_tie_groups
from night_shift.models import HistoryInput, RecordKind
from night_shift.solver import solve_first_trial
from tests.test_big_rest_rotation import _record, _last_rest_ids, _big_rest_ids


class RestAverageTieTests(unittest.TestCase):
    def test_exact_average_ties_and_missing_history(self):
        av = {'1': Fraction(40, 3), '2': Fraction(41, 3), '3': Fraction(40, 3)}
        self.assertEqual(rest_tie_groups(['1', '2', '3'], av), [['2']])
        self.assertEqual(rest_tie_groups(['1', '3'], av), [])
        self.assertEqual(rest_tie_groups(['1', '4'], av), [])

    def test_only_six_actual_records_before_target(self):
        records = [_record(date(2026, 10, d)) for d in range(4, 12)]
        records = [replace(r, assignments=tuple(
            replace(x, fatigue_value=x.fatigue_value + r.context.shift_start_date.day)
            if x.employee_id == '1' and x.slot.index == 0 else x for x in r.assignments)) for r in records]
        records += [replace(_record(date(2026, 10, 12)), kind=RecordKind.PLAN, confirmed_at=None)]
        target = date(2026, 10, 11)
        av = recent_six_fatigue_averages(records, target)
        expected = recent_six_fatigue_averages(records[1:7], target)
        self.assertEqual(av, expected)
        self.assertEqual(av['1'], Fraction(57, 2))  # 21 + (5+6+7+8+9+10)/6

    def test_partial_uses_peer_average_and_absence_is_not_zero(self):
        def person(fatigue, available=14, manager=False):
            return SimpleNamespace(fatigue_value=fatigue, available_time=available, is_manager=manager)
        records = [_record(date(2026,10,15)), _record(date(2026,10,16))]
        with patch('night_shift.service.calculate_all_stats', side_effect=[
                {'1':person(2,7), '2':person(12), '3':person(14), 'A':person(1,manager=True)},
                {'1':person(15), '2':person(13), 'A':person(1,manager=True)}]):
            av = recent_six_fatigue_averages(records, date(2026,10,22))
        self.assertEqual(av['1'], 14)  # (당일 동료 평균13 + 다음날15)/2
        self.assertEqual(av['3'], 14)  # 미출근은 0점으로 더하지 않는다

    def test_solver_ties_choose_higher_average_for_both_rest_types(self):
        past = _record(date(2026, 10, 15), big_rest_pids=('1','2','3','4','5','6'))
        # 모두 같은 날 수혜. 막타임은 다음 출근 금지이므로 중간 출근 1회 둔다.
        past = replace(past, assignments=tuple(
            replace(x, actual_rest_time_value=1, fatigue_value=0) if x.slot.index == 13 and x.employee_id != 'A' else x
            for x in past.assignments))
        middle = _record(date(2026, 10, 16), last_rest_pid='3')
        # 순번은 같고 1번의 실제 피로도만 높게 만들어 동점 우선 방향을 검증한다.
        middle = replace(middle, assignments=tuple(
            replace(x, fatigue_value=3) if x.employee_id == '1' else x for x in middle.assignments))
        current = _record(date(2026, 10, 22))
        solved = solve_first_trial(current.context, HistoryInput((),()), seconds=15, rules_v220=True,
                                   last_rest_records=(past, middle))
        self.assertIsNotNone(solved.record, solved.status)
        self.assertEqual(_last_rest_ids(solved.record), {'1'})
        self.assertIn('1', _big_rest_ids(solved.record))
        stages = [a.get('stage','') for a in solved.attempts]
        self.assertTrue(any(s.startswith('last_rest_oldest_') and '_avg_' in s for s in stages), stages)
        self.assertTrue(any(s.startswith('big_rest_oldest_') and '_avg_' in s for s in stages), stages)
