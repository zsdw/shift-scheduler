"""2026-10-05 사용자 확정:
H-12-1 [하드] 통제A 21시 상층 순찰 직전 20시에 실근무가 없으면 22·23시 중 한 칸은 근무 가능(나머지 한 칸 휴게).
17-4 [강한 권장] 통제A 00시 이후 연속 휴게 2시간 (관리자 우대 바로 다음)."""
import unittest
from datetime import date

from night_shift import history_import as imp
from night_shift.models import HistoryInput, Mode, NightType
from night_shift.service import HistorySelection, ShiftRequest, SolveOptions, StaffInput, run_schedule
from night_shift.validator import validate_first_trial

NAMES = {"1": "만년", "2": "원종", "3": "제욱", "4": "광희", "5": "성호", "6": "준호"}


def a_errors(a_cells):
    grid = {t: ["휴게"] * 14 for t in ("A", *NAMES)}
    grid["A"][3] = "상층순찰"
    for t, label in a_cells.items():
        grid["A"][t] = label
    record = imp.build_import_record(date(2026, 10, 6), Mode.FM, grid, {t: t for t in grid}, imp.ROSTER)
    return {(e["rule"]) for e in validate_first_trial(record, HistoryInput((), ()), rules_v220=True)
            if e["detail"].split()[-1].startswith("A") or "A/" in e["detail"] or e["detail"].endswith(" A")}


class ManagerPatrolRestTests(unittest.TestCase):
    def test_validator(self):
        self.assertNotIn("H-12-1", a_errors({4: "L3"}))                 # 20시 휴게 → 22시 근무 OK
        self.assertNotIn("H-11", a_errors({5: "G1"}))                   # 23시 근무도 OK
        self.assertIn("H-12-1", a_errors({4: "L3", 5: "G1"}))           # 둘 다 근무는 금지
        self.assertIn("H-11", a_errors({2: "G1", 4: "L3"}))             # 20시 근무했으면 22·23 모두 휴게

    def test_generated_tables(self):
        staff = [StaffInput("A", "통제", True, False, None, True)]
        staff += [StaffInput(p, n, True, True, int(p), False) for p, n in NAMES.items()]
        for day, night in ((date(2026, 10, 6), NightType.N1), (date(2026, 10, 9), NightType.N4)):
            with self.subTest(night=night):
                result = run_schedule(ShiftRequest(day, night, Mode.FM, tuple(staff)), HistorySelection(),
                                      SolveOptions(rules_version="2.20", seconds=20))
                self.assertTrue(result.valid, result.validation_errors or result.solve_result.status)
                rest = [r.actual_rest_time_value for r in sorted(
                    (r for r in result.record.assignments if r.employee_id == "A"), key=lambda r: r.slot.index)]
                self.assertTrue(any(rest[t] and rest[t + 1] for t in range(6, 13)), rest)   # 00시 이후 연속 휴게 2시간


if __name__ == "__main__":
    unittest.main()
