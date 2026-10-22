"""🧪 테스트 생성 버튼 규칙 (2026-10-23 사용자 요청, 실제 생성에는 적용 안 함):
다음날 평일·통제A 온전 출근·결원 0~1명이면 H-15 실근무 차이 3시간 이내, 통제A 피로도 = 각 일반근무자보다 4~6점 낮게,
결원 0명은 03시 통제A 휴게성 권장. Validator도 같은 값으로 검사하고, 범위 밖 날은 지금 규칙 그대로."""
import unittest
from datetime import date

from night_shift.models import HistoryInput, Mode, NightType
from night_shift.service import (HistorySelection, ShiftRequest, SolveOptions, StaffInput, build_context,
                                 run_schedule, test_relief_applies)
from night_shift.validator import validate_first_trial

NAMES = {"1": "만년", "2": "원종", "3": "제욱", "4": "광희", "5": "성호", "6": "준호"}
DAY = date(2026, 10, 27)


def staff(absent=(), a_present=True):
    rows = [StaffInput("A", "통제", a_present, False, None, True)]
    for p, n in NAMES.items():
        proxy = p == "6" and not a_present
        rows.append(StaffInput(p, n, p not in absent, not proxy, int(p), proxy))
    return tuple(rows)


def totals(record, key):
    out = {}
    for r in record.assignments:
        out[r.employee_id] = out.get(r.employee_id, 0) + getattr(r, key)
    return out


def rules(record, relief):
    return {e["rule"] for e in validate_first_trial(record, HistoryInput((), ()), rules_v220=True,
                                                    test_manager_relief=relief)}


class TestManagerReliefTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        request = ShiftRequest(DAY, NightType.N1, Mode.FM, staff())
        cls.test = run_schedule(request, HistorySelection(), SolveOptions(rules_version="2.20", seconds=20,
                                                                          test_manager_relief=True))
        cls.normal = run_schedule(request, HistorySelection(), SolveOptions(rules_version="2.20", seconds=20))

    def test_generated_table_keeps_four_to_six_gap_and_three_hour_work_gap(self):
        self.assertTrue(self.test.valid, self.test.validation_errors)
        self.assertTrue(self.test.test_manager_relief)
        fatigue, work = totals(self.test.record, "fatigue_value"), totals(self.test.record, "actual_work_time_value")
        for p in NAMES:
            self.assertTrue(4 <= fatigue[p] - fatigue["A"] <= 6, (p, fatigue))
            self.assertLessEqual(abs(work[p] - work["A"]), 3, (p, work))
        a04 = next(r for r in self.test.record.assignments if r.employee_id == "A" and r.slot.index == 10)
        self.assertEqual(a04.actual_work_time_value, 0)          # 결원 0명 04시 휴게 하드(8-10-2) 그대로

    def test_validator_uses_the_band_both_ways(self):
        # 테스트 규칙 표를 지금 규칙으로 보면 8-4-2 위반(4점 이상), 지금 규칙 표를 테스트 규칙으로 보면 위반(4점 미만)
        self.assertIn("8-4-2", rules(self.test.record, False))
        self.assertTrue(self.normal.valid)
        self.assertIn("8-4-2", rules(self.normal.record, True))
        self.assertNotIn("8-4-2", rules(self.test.record, True))

    def test_out_of_scope_days_keep_current_rules(self):
        options = SolveOptions(rules_version="2.20", test_manager_relief=True)
        self.assertTrue(test_relief_applies(build_context(ShiftRequest(DAY, NightType.N1, Mode.FM, staff(("1",)))), options))
        self.assertFalse(test_relief_applies(build_context(ShiftRequest(DAY, NightType.N2, Mode.FM, staff())), options))
        self.assertFalse(test_relief_applies(build_context(ShiftRequest(DAY, NightType.N1, Mode.FM, staff(("1", "2")))), options))
        self.assertFalse(test_relief_applies(build_context(ShiftRequest(DAY, NightType.N1, Mode.FM, staff(a_present=False))), options))
        self.assertFalse(test_relief_applies(build_context(ShiftRequest(DAY, NightType.N1, Mode.FM, staff())),
                                             SolveOptions(rules_version="2.20")))


if __name__ == "__main__":
    unittest.main()
