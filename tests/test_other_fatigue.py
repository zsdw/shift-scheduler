"""직원 비교표 '기타 피로도' (2026-10-05 사용자 요청): 피로도 = 입식×2 + 좌식×1 + 순찰 점수 + 기타 피로도."""
import unittest
from datetime import date

from night_shift.actual_edit import apply_edits
from night_shift.models import Mode, NightType
from night_shift.service import (HistorySelection, ShiftRequest, SolveOptions, StaffInput, calculate_all_stats,
                                 run_schedule)

NAMES = {"1": "만년", "2": "원종", "3": "제욱", "4": "광희", "5": "성호", "6": "준호"}


class OtherFatigueTests(unittest.TestCase):
    def test_identity_and_field_note(self):
        staff = (StaffInput("A", "통제", True, False, None, True),
                 *(StaffInput(p, n, True, True, int(p), False) for p, n in NAMES.items()))
        result = run_schedule(ShiftRequest(date(2026, 10, 10), NightType.N4, Mode.FM, staff), HistorySelection(),
                              SolveOptions(rules_version="2.20", seconds=15))
        for p in result.employee_stats.values():           # 피로도 = 입식×2 + 좌식 + 순찰 피로도 + 기타
            self.assertEqual(p.fatigue_value, 2 * p.post_standing + p.post_seated + p.patrol_fatigue + p.other_fatigue)
            self.assertFalse(any("순찰" in why for why in p.other_fatigue_reasons))   # 순찰은 기타에 안 씀
        lower = next(r for r in result.record.assignments if r.actual_post_or_work_type.label == "lower")
        self.assertEqual(result.employee_stats[lower.employee_id].patrol_reasons, ("하층",))   # 하층만 표시
        upper = next(r for r in result.record.assignments if r.actual_post_or_work_type.label == "upper"
                     and r.employee_id != lower.employee_id)
        self.assertNotIn("하층", result.employee_stats[upper.employee_id].patrol_reasons)
        # 2026-10-09 야간부터 차단봉 단독 담당(20시 G2/I1 혼자, 04시 I1 혼자) → 대기자 설치 없음, 대기 차단봉 +1도 없음
        self.assertFalse([r for r in result.record.assignments
                          if (r.barrier_install_flag or r.barrier_remove_flag) and r.displayed_assignment.label == "보안실 대기"])
        self.assertFalse(any("대기 차단봉" in why for p in result.employee_stats.values() for why in p.other_fatigue_reasons))
        posters = {r.employee_id for r in result.record.assignments           # 포스트로 설치·철수한 사람은 기타 없음
                   if (r.barrier_install_flag or r.barrier_remove_flag) and r.displayed_assignment.label != "보안실 대기"}
        for pid in posters:
            self.assertFalse(any("차단봉" in why for why in result.employee_stats[pid].other_fatigue_reasons))
        cell = next(r for r in result.record.assignments
                    if r.employee_id == "2" and r.displayed_assignment.label == "I1" and r.fatigue_value == 1)
        edited = apply_edits(result.record, [{"type": "fatigue", "cell": ["2", cell.slot.index], "value": 2,
                                              "note": "현장 사유"}])
        after = calculate_all_stats(edited)["2"]
        self.assertEqual(after.other_fatigue, result.employee_stats["2"].other_fatigue + 1)   # 현장 주석 +1
        hour = f"{(18 + cell.slot.index) % 24:02d}시"
        self.assertIn(f"{hour} I1 현장 피로도 주석 +1", after.other_fatigue_reasons)


if __name__ == "__main__":
    unittest.main()
