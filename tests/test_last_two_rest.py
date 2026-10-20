"""막타임 2시간 연속 휴게 금지 (2026-10-20 사용자 확정, 하드, 결원 무관).

야간 H-20: 일반근무자 신분 06·07시 연속 휴게(휴게·업무 없는 대기, FM 표기) 금지.
빨간날 주간: 일반근무자 신분 16·17시 연속 휴게(휴게·대기) 금지. 통제A·준호 관리자 대행은 예외.
"""
import unittest
from copy import deepcopy
from dataclasses import replace
from datetime import date

from night_shift import history_import as imp
from night_shift.models import HistoryInput, Mode
from night_shift.solver import solve_first_trial
from night_shift.validator import validate_first_trial
from night_shift.weekend_day import generate, validate

REST = ("휴게", "보안실 대기")


def night_context(day, absent=()):
    grid = {p: ['G1'] * 14 for p in ('A', '1', '2', '3', '4', '5', '6')}
    record = imp.build_import_record(day, Mode.FM, grid, {p: p for p in grid}, imp.ROSTER)
    att = tuple(replace(a, present=False, available_slot_indices=None) if a.employee_id in absent else a
                for a in record.context.attendance)
    return replace(record.context, attendance=att)


def h20(record):
    return [e for e in validate_first_trial(record, HistoryInput((), ()), rules_v220=True) if e['rule'] == 'H-20']


class NightLastTwoRestTests(unittest.TestCase):
    def test_generated_tables_have_no_general_06_07_rest(self):
        # 다음날 평일(N1) 결원 0명 · 다음날 공휴일(N4) 결원 1명: 휴게 자리가 많은 날도 연속 휴게 없음
        for day, absent in ((date(2026, 10, 22), ()), (date(2026, 10, 24), ('5',))):
            solved = solve_first_trial(night_context(day, absent), HistoryInput((), ()), seconds=20, rules_v220=True)
            self.assertIsNotNone(solved.record, solved.status)
            self.assertFalse(h20(solved.record))
            cell = {(r.employee_id, r.slot.index): r.displayed_assignment.label for r in solved.record.assignments}
            for pid in ('1', '2', '3', '4', '6'):
                self.assertFalse(cell[pid, 12] in REST and cell[pid, 13] in REST, pid)

    def test_validator_rejects_general_rest_06_07(self):
        # 규칙을 끄고 일반근무자 1번에게 06·07시 휴게를 강제한 표 → Validator가 따로 거부
        solved = solve_first_trial(night_context(date(2026, 10, 24)), HistoryInput((), ()), seconds=20, rules_v220=True,
                                   disabled_rule_groups=frozenset({"H-20 06·07시 휴게 2연속 금지"}),
                                   forced_rest_cells=(('1', 12), ('1', 13)))
        self.assertIsNotNone(solved.record, solved.status)
        cell = {(r.employee_id, r.slot.index): r.displayed_assignment.label for r in solved.record.assignments}
        self.assertTrue(cell['1', 12] in REST and cell['1', 13] in REST)
        self.assertTrue(any(': 1' in e['detail'] for e in h20(solved.record)))

    def test_manager_rest_06_07_is_allowed(self):
        solved = solve_first_trial(night_context(date(2026, 10, 24)), HistoryInput((), ()), seconds=20, rules_v220=True,
                                   forced_rest_cells=(('A', 12), ('A', 13)))
        self.assertIsNotNone(solved.record, solved.status)
        self.assertFalse(h20(solved.record))


class WeekendLastTwoRestTests(unittest.TestCase):
    def test_generated_and_rejected(self):
        names = {'A': '통제A', **{str(i): str(i) for i in range(1, 6)}}      # 결원 1명
        s, status = generate('2026-10-25', names, 'FM', seconds=30)
        self.assertIsNotNone(s, status)
        self.assertFalse(validate(s))
        for pid, row in s.grid.items():
            if pid != 'A':
                self.assertFalse(row[8] in ('휴게', '대기') and row[9] in ('휴게', '대기'), pid)
        bad = deepcopy(s)
        pid = next(p for p in bad.grid if p != 'A')
        bad.grid[pid][8:10] = ['휴게', '대기']
        self.assertTrue(any('16·17시 연속 휴게 금지' in e for e in validate(bad)))
        ok = deepcopy(s)
        ok.grid['A'][8:10] = ['휴게', '휴게']                               # 통제A는 관리자 역할 예외
        self.assertFalse(any('16·17시 연속 휴게 금지' in e for e in validate(ok)))


if __name__ == '__main__':
    unittest.main()
