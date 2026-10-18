"""표시 메모 (2026-10-02 사용자 요청): 평일 시작 야간(N1·N2) 통제 18시 L3는 실제로 보안실 대기라
'실제 보안실 대기'를 적는다. 유도리 기본 I1 00~03시 휴게성 칸은 굵은 띠로만 표시(메모 없음)."""
import unittest
from datetime import date

import app
from night_shift.models import Mode, NightType
from night_shift.presentation import assignment_view
from night_shift.service import ShiftRequest, SolveOptions, run_schedule

OPTIONS = SolveOptions(rules_version="2.20", seconds=15)


def staff():
    return app.staff_for_input(True, {eid: True for eid, _ in app.ROSTER})


class DisplayNoteTests(unittest.TestCase):
    def test_weekday_start_manager_18_l3_shows_actual_standby(self):
        result = run_schedule(ShiftRequest(date(2026, 10, 5), NightType.N1, Mode.FM, staff()), None, OPTIONS)
        self.assertTrue(result.valid)
        row = next(r for r in result.record.assignments if r.employee_id == "A" and r.slot.index == 0)
        label, notes, _, _ = assignment_view(row, result.record.context)
        self.assertEqual(label, "L3")
        self.assertIn("실제 보안실 대기", notes)

    def test_default_flexible_i1_rest_has_no_note(self):
        result = run_schedule(ShiftRequest(date(2026, 10, 5), NightType.N1, Mode.FLEXIBLE, staff()), None, OPTIONS)
        self.assertTrue(result.valid)
        for row in result.record.assignments:
            if row.displayed_assignment.label == "I1" and 6 <= row.slot.index <= 9:
                notes = assignment_view(row, result.record.context)[1]
                self.assertFalse([n for n in notes if "휴게성" in n], notes)

    def test_rulebook_label_shows_current_rulebook(self):
        # 화면 '룰북' 칸이 v2.20으로 나오던 문제: 엔진 분기값 2.20 = 룰북 v2.21
        from night_shift.service import rulebook_label
        self.assertEqual(rulebook_label("2.20"), "v2.21")
        self.assertEqual(rulebook_label("2.13"), "v2.13")


if __name__ == "__main__":
    unittest.main()
