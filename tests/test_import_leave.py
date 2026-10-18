"""2026-10-05: 가져온 야간 기록에서 반차·연차 시간은 휴게가 아니라 근무불가(×) (룰북 21-7)."""
import unittest
from datetime import date

from night_shift import history_import as imp
from night_shift import leave_schedule
from night_shift.models import AssignmentKind, Mode
from night_shift.service import calculate_all_stats

DAY = date(2026, 10, 4)
IDS = {t: t for t in ("A", "1", "2", "3", "4", "5", "6")}       # 번호 = 직원 ID (6 = 준호)
NAMES = {t: ("A" if t == "A" else imp.ROSTER[t]) for t in IDS}


def grid():
    return {t: ["휴게"] * 14 for t in IDS}


class ImportLeaveTests(unittest.TestCase):
    def test_slots(self):
        self.assertEqual(leave_schedule.night_unavailable_slots(leave_schedule.NIGHT_FIRST), set(range(7)))
        self.assertEqual(leave_schedule.night_unavailable_slots(leave_schedule.NIGHT_LATE), set(range(7, 14)))
        self.assertEqual(leave_schedule.night_unavailable_slots("연차"), set(range(14)))

    def test_first_half_leave_is_unavailable_not_rest(self):
        fixed, notes = imp.apply_leave(grid(), NAMES, {"준호": (leave_schedule.NIGHT_FIRST, "")})
        self.assertEqual(fixed["6"][:7], ["근무불가"] * 7)
        self.assertEqual(fixed["6"][7:], ["휴게"] * 7)
        record = imp.build_import_record(DAY, Mode.FM, fixed, IDS, imp.ROSTER)
        rows = [r for r in record.assignments if r.employee_id == "6"]
        self.assertTrue(all(r.displayed_assignment.kind == AssignmentKind.UNAVAILABLE for r in rows if r.slot.index < 7))
        self.assertEqual(calculate_all_stats(record)["6"].actual_rest_time_value, 7)   # 14 아님
        self.assertTrue(notes)

    def test_work_inside_leave_hours_is_left_alone(self):
        g = grid()
        g["6"][3] = "G1"                                   # 반차 시간에 근무 기록 = 반차 취소·계획표일 수 있음
        fixed, notes = imp.apply_leave(g, NAMES, {"준호": (leave_schedule.NIGHT_FIRST, "")})
        self.assertNotIn("근무불가", fixed["6"])
        self.assertIn("확인", notes[0])

    def test_fix_saved_record(self):
        record = imp.build_import_record(DAY, Mode.FM, grid(), IDS, imp.ROSTER)
        fixed, cells = imp.leave_fix_record(record, {"6": set(range(7))})
        self.assertEqual(len(cells), 7)
        self.assertEqual(calculate_all_stats(fixed)["6"].actual_rest_time_value, 7)
        att = next(a for a in fixed.context.attendance if a.employee_id == "6")
        self.assertEqual(att.available_slot_indices, tuple(range(7, 14)))


if __name__ == "__main__":
    unittest.main()
