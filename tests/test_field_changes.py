"""2026-10-05 사용자 확정: 근무표 특이사항은 생성 당시 기준(현장 변동 제외). 현장에서 생긴 교환·피로도 주석
변동은 월간 분석에서 '날짜 · 누구 · 몇 시 · 사유(주석) · 피로도 변화'로 설명한다."""
import unittest
from datetime import date

from history_ui import field_changes
from night_shift.actual_edit import apply_edits
from night_shift.balance_notes import monthly_direction
from night_shift.models import Mode, NightType
from night_shift.service import HistorySelection, ShiftRequest, SolveOptions, StaffInput, run_schedule

NAMES = {"1": "만년", "2": "원종", "3": "제욱", "4": "광희", "5": "성호", "6": "준호"}


class FieldChangesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        staff = (StaffInput("A", "통제", True, False, None, True),
                 *(StaffInput(p, n, True, True, int(p), False) for p, n in NAMES.items()))
        cls.plan = run_schedule(ShiftRequest(date(2026, 10, 6), NightType.N1, Mode.FM, staff), HistorySelection(),
                                SolveOptions(rules_version="2.20", seconds=15)).record

    def test_fatigue_note_is_listed_with_date_hour_reason(self):
        cell = next(r for r in self.plan.assignments                     # 피로도 1인 일반 I1 칸 (18시 I1은 실제 L3라 2점)
                    if r.employee_id == "4" and r.displayed_assignment.label == "I1" and r.fatigue_value == 1)
        edits = [{"type": "fatigue", "cell": ["4", cell.slot.index], "value": 2, "note": "I1 민원 대응"}]
        actual = apply_edits(self.plan, edits)
        rows = field_changes(date(2026, 10, 6), self.plan, actual, edits, {**NAMES, "A": "통제"})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["직원"], "광희")
        self.assertIn("피로도 2로 변경 — I1 민원 대응", rows[0]["내용"])
        self.assertEqual(rows[0]["피로도 변화"], "+1")
        lines = monthly_direction([{"직원": "광희", "평균 피로도": 15.0, "현장 변동": rows},
                                   {"직원": "만년", "평균 피로도": 15.0}])
        self.assertTrue(any("10/06" in line and "주석 참조" in line and "+1점" in line for line in lines), lines)

    def test_no_edits_no_changes(self):
        self.assertEqual(field_changes(date(2026, 10, 6), self.plan, self.plan, [], NAMES), [])


if __name__ == "__main__":
    unittest.main()
