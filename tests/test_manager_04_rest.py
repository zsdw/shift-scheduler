"""8-10 [하드, 2026-10-05 사용자 확정]: 통제A 04시 보안실 대기 금지(쉬면 '휴게')·차단봉 철수 불참."""
import unittest
from datetime import date

from night_shift import history_import as imp
from night_shift.models import HistoryInput, Mode, NightType
from night_shift.service import HistorySelection, ShiftRequest, SolveOptions, StaffInput, run_schedule
from night_shift.validator import validate_first_trial

NAMES = {"1": "만년", "2": "원종", "3": "제욱", "4": "광희", "5": "성호", "6": "준호"}


def staff(absent=()):
    rows = [StaffInput("A", "통제", True, False, None, True)]
    number = 0
    for p, n in NAMES.items():
        present = p not in absent
        number += present
        rows.append(StaffInput(p, n, present, True, number if present else None, False))
    return tuple(rows)


class Manager04Tests(unittest.TestCase):
    def test_generated(self):
        for day, night, absent in ((date(2026, 10, 6), NightType.N1, ()), (date(2026, 10, 9), NightType.N4, ()),
                                   (date(2026, 10, 6), NightType.N1, ("3", "4"))):
            with self.subTest(night=night, absent=absent):
                result = run_schedule(ShiftRequest(day, night, Mode.FM, staff(absent)), HistorySelection(),
                                      SolveOptions(rules_version="2.20", seconds=20))
                self.assertTrue(result.valid, result.validation_errors or result.solve_result.status)
                rows = [r for r in result.record.assignments if r.employee_id == "A"]
                four = next(r for r in rows if r.slot.index == 10)
                self.assertNotEqual(four.displayed_assignment.label, "보안실 대기")
                self.assertFalse(any(r.barrier_remove_flag for r in rows))

    def test_validator_rejects_standby_and_removal(self):
        grid = {t: ["휴게"] * 14 for t in ("A", *NAMES)}
        grid["A"][10] = "보안실 대기"
        # 대기자 철수 칸은 옛 규칙 날짜(~10/4)에만 만들 수 있다 (10/5~ 15-0은 철수 = I1 근무자뿐)
        record = imp.build_import_record(date(2026, 10, 3), Mode.FM, grid, {t: t for t in grid}, imp.ROSTER,
                                         removes=[("A", 10)])
        rules = [e for e in validate_first_trial(record, HistoryInput((), ()), rules_v220=True) if e["rule"] == "8-10"]
        self.assertEqual(len(rules), 2)


if __name__ == "__main__":
    unittest.main()
