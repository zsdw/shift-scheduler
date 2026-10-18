"""긴급 피로도 1 우선, 불가능 증명 후 2, 초과표 거부 회귀."""
import unittest
from copy import deepcopy
from ortools.sat.python import cp_model
from night_shift.weekend_day import (
    _solve_emergency_fatigue, generate, reoptimize, validate, stats, partial_people,
    WeekendSchedule,
)
from tests.test_weekend_actual_edit import GRID, NAMES


class EmergencyFatigueTests(unittest.TestCase):
    def test_one_beats_other_objectives(self):
        model = cp_model.CpModel()
        gap = model.NewIntVar(0, 3, 'gap')
        model.Minimize(-1000000 * gap)  # 다른 목표가 큰 격차를 선호해도 상한 우선
        calls = []
        def solve(probe, seconds):
            solver = cp_model.CpSolver()
            calls.append(seconds)
            return solver, solver.Solve(probe)
        solver, status, limit = _solve_emergency_fatigue(model, [gap], solve, 3)
        self.assertEqual(limit, 1)
        self.assertEqual(solver.Value(gap), 1)
        self.assertEqual(len(calls), 1)

    def test_two_only_after_infeasible_and_never_three(self):
        for minimum, expected in ((2, cp_model.OPTIMAL), (3, cp_model.INFEASIBLE)):
            model = cp_model.CpModel()
            gap = model.NewIntVar(minimum, 3, 'gap')
            calls = []
            def solve(probe, seconds):
                solver = cp_model.CpSolver()
                status = solver.Solve(probe)
                calls.append(status)
                return solver, status
            solver, status, limit = _solve_emergency_fatigue(model, [gap], solve, 3)
            self.assertEqual(calls[0], cp_model.INFEASIBLE)
            self.assertEqual((status, limit), (expected, 2))
            if status == cp_model.OPTIMAL:
                self.assertEqual(solver.Value(gap), 2)

    def test_unknown_does_not_relax(self):
        calls = []
        def solve(model, seconds):
            calls.append(seconds)
            return None, cp_model.UNKNOWN
        _, status, limit = _solve_emergency_fatigue(cp_model.CpModel(), [], solve, 3)
        self.assertEqual((status, limit, len(calls)), (cp_model.UNKNOWN, 1, 1))

    def test_ui_explains_proven_relaxation_and_legacy_candidates(self):
        from streamlit.testing.v1 import AppTest
        app = AppTest.from_string('''
import streamlit as st
from copy import deepcopy
from night_shift.weekend_day import WeekendSchedule
from weekend_day_ui import nbbang_text
from tests.test_weekend_actual_edit import GRID, NAMES
s = WeekendSchedule(day='2026-10-25', names=NAMES, grid=deepcopy(GRID),
                    leavers={'1': {'from': 5, 'kind': 'half', 'lock': 4}}, locked_through=4)
st.markdown(nbbang_text(s, 'EMERGENCY_GAP_2'))
st.markdown(nbbang_text(s, 'GAP_OVER'))
''').run()
        self.assertFalse(app.exception)
        text = '\n'.join(m.value for m in app.markdown)
        self.assertIn('1 이내의 해가 없음을 확인', text)
        self.assertIn('재생성해 주세요', text)
        self.assertNotIn('LOCK 10시까지', text)

    def test_validator_rejects_three_even_when_relaxed(self):
        schedule = WeekendSchedule(day='2026-10-25', names=NAMES,
                                   grid=deepcopy(GRID), locked_through=4,
                                   leavers={'1': {'from': 5, 'kind': 'half', 'lock': 4}},
                                   relaxed=True)
        schedule.grid['2'] = ['휴게'] * 10
        errors = validate(schedule)
        self.assertTrue(any('피로도 격차 초과' in e and '상한 2' in e for e in errors), errors)

    def test_planned_half_plus_emergency_keeps_lock_and_gap(self):
        names = {'A': '통제A', **{str(i): str(i) for i in range(1, 7)}}
        base, status = generate('2026-10-25', names, 'FM', seconds=20,
                                half_days={'3': '오전반차'})
        self.assertIsNotNone(base, status)
        result, status = reoptimize(base, 4, '2', 'half', seconds=30)
        self.assertIsNotNone(result, status)
        self.assertIn(status, ('EMERGENCY_GAP_1', 'EMERGENCY_GAP_2'))
        self.assertEqual(validate(result, base), [])
        for pid in base.grid:
            self.assertEqual(result.grid[pid][:5], base.grid[pid][:5])
        for mode in ('FM', '유도리'):
            values = [row['피로도'] for pid, row in zip(result.grid, stats(result, mode))
                      if pid != 'A' and pid not in partial_people(result)]
            self.assertLessEqual(max(values) - min(values), 1 if status.endswith('_1') else 2)


if __name__ == '__main__':
    unittest.main()
