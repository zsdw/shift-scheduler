"""8-11 [하드, 2026-10-05 사용자 확정]: 당일 관리자(통제A·관리자대행) 18시·07시 실근무 없음.
예외: N1/N3 07시 가용 일반근무자 4명(8-3-1)이면 07시 근무 허용."""
import unittest
from datetime import date

from night_shift import history_import as imp
from night_shift.models import HistoryInput, Mode, NightType
from night_shift.service import HistorySelection, ShiftRequest, SolveOptions, StaffInput, run_schedule
from night_shift.validator import validate_first_trial

NAMES = {"1": "만년", "2": "원종", "3": "제욱", "4": "광희", "5": "성호", "6": "준호"}


def staff(absent=(), a_absent=False):
    """app.staff_for_input과 같은 모양: 관리자대행 준호 = 일반근무자 아님 + 관리자, 번호 유지."""
    rows = [StaffInput("A", "통제", not a_absent, False, None, not a_absent)]
    for p, n in NAMES.items():
        proxy = a_absent and p == "6"
        rows.append(StaffInput(p, n, p not in absent, not proxy, int(p), proxy))
    return tuple(rows)


def work(result, who, slot):
    return next(r for r in result.record.assignments if r.employee_id == who and r.slot.index == slot).actual_work_time_value


class ManagerFirstLastTests(unittest.TestCase):
    def test_generated(self):
        cases = ((date(2026, 10, 6), NightType.N1, (), False, "A", True),
                 (date(2026, 10, 9), NightType.N4, (), False, "A", True),
                 (date(2026, 10, 9), NightType.N4, ("3",), True, "6", True),       # 준호 관리자대행
                 (date(2026, 10, 6), NightType.N1, ("3", "4"), False, "A", False))  # 8-3-1: 07시 근무 허용
        for day, night, absent, a_absent, boss, last_free in cases:
            with self.subTest(night=night, absent=absent, a_absent=a_absent):
                result = run_schedule(ShiftRequest(day, night, Mode.FM, staff(absent, a_absent)), HistorySelection(),
                                      SolveOptions(rules_version="2.20", seconds=20))
                self.assertTrue(result.valid, result.validation_errors or result.solve_result.status)
                self.assertEqual(work(result, boss, 0), 0)
                if last_free:
                    self.assertEqual(work(result, boss, 13), 0)

    def test_validator_rejects_last_slot_work(self):
        grid = {t: ["휴게"] * 14 for t in ("A", *NAMES)}
        grid["A"][13] = "L3"
        record = imp.build_import_record(date(2026, 10, 7), Mode.FM, grid, {t: t for t in grid}, imp.ROSTER)
        rules = {e["rule"] for e in validate_first_trial(record, HistoryInput((), ()), rules_v220=True)}
        self.assertIn("8-11", rules)


if __name__ == "__main__":
    unittest.main()
