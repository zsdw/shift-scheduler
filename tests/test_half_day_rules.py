"""H-09-1 (2026-10-05 사용자 확정): 미리 정한 야간 반차자는
- 순찰 후 2시간 휴게가 하드가 아니다(입식→순찰→입식만 금지, 휴게는 밸런스 다음 권장).
- 다른 근무자 밸런스를 위해 피로도·실근무가 더 많아도 된다(일반 n빵 비교에서 빠짐, 기존).
- 나오는 시간 안에서 실제 휴게 합계 2시간 이상은 하드."""
import unittest
from dataclasses import replace
from datetime import date

from night_shift.models import HistoryInput, Mode, NightType
from night_shift.service import (HistorySelection, ShiftRequest, SolveOptions, StaffInput, run_reoptimization,
                                 run_schedule)
from night_shift.validator import validate_first_trial

NAMES = {"1": "만년", "2": "원종", "3": "제욱", "4": "광희", "5": "성호", "6": "준호"}
LATE, EARLY = tuple(range(7)), tuple(range(7, 14))      # 후반부 반차(01시 퇴근), 전반부 반차(01시 출근)


def staff(slots):
    return (StaffInput("A", "통제", True, False, None, True),
            *(StaffInput(p, n, True, True, int(p), False, slots.get(p)) for p, n in NAMES.items()))


def rest_hours(record, who):
    return sum(r.actual_rest_time_value for r in record.assignments if r.employee_id == who)


class HalfDayTests(unittest.TestCase):
    def test_generated_half_day_rest_at_least_two(self):
        for day, night, slots in ((date(2026, 10, 6), NightType.N1, {"4": LATE}),
                                  (date(2026, 10, 10), NightType.N4, {"6": EARLY}),
                                  (date(2026, 10, 6), NightType.N1, {"4": LATE, "6": EARLY})):
            with self.subTest(night=night, slots=list(slots)):
                result = run_schedule(ShiftRequest(day, night, Mode.FM, staff(slots)), HistorySelection(),
                                      SolveOptions(rules_version="2.20", seconds=20))
                self.assertTrue(result.valid, result.validation_errors or result.solve_result.status)
                for who in slots:
                    self.assertGreaterEqual(rest_hours(result.record, who), 2)

    def test_validator(self):
        result = run_schedule(ShiftRequest(date(2026, 10, 6), NightType.N1, Mode.FM, staff({"4": LATE})),
                              HistorySelection(), SolveOptions(rules_version="2.20", seconds=20))
        from night_shift.profiles import make_record
        rows = list(result.record.assignments)
        # 위반표: 반차자의 휴게 칸을 모두 G1 근무 배정으로 바꿈 → 휴게 2시간 미만 (검증기가 칸 배정으로 다시 계산)
        for i, r in enumerate(rows):
            if r.employee_id == "4" and r.actual_rest_time_value == 1 and r.displayed_assignment.label == "휴게":
                rows[i] = make_record(result.record.context, "4", r.slot.index, "G1", patrol_standing=True)
        bad = replace(result.record, assignments=tuple(rows))
        rules = {e["rule"] for e in validate_first_trial(bad, HistoryInput((), ()), rules_v220=True)}
        self.assertIn("H-09-1", rules)

    def test_emergency_keeps_planned_half_day(self):
        base = run_schedule(ShiftRequest(date(2026, 10, 6), NightType.N1, Mode.FM, staff({"4": LATE})),
                            HistorySelection(), SolveOptions(rules_version="2.20", seconds=20))
        outcome = run_reoptimization(base, 3, "2", 3, HistorySelection(), SolveOptions(rules_version="2.20", seconds=20),
                                     "긴급 이탈 (선택 시간부터)")
        self.assertTrue(outcome.valid, outcome.validation_errors or outcome.solve_result.status)
        self.assertGreaterEqual(rest_hours(outcome.record, "4"), 2)        # 미리 정한 반차자 규칙 유지


if __name__ == "__main__":
    unittest.main()
