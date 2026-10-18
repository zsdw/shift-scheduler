"""FM 보안실 대기: 20·04시 외에는 비근무자 2명 이상이면 1명만, 나머지는 휴게, 고르게 분배."""
import unittest
from datetime import date

from night_shift.models import Mode, NightType
from night_shift.service import HistorySelection, ShiftRequest, SolveOptions, StaffInput, run_schedule

NAMES = {"1": "만년", "2": "원종", "3": "제욱", "4": "광희", "5": "성호", "6": "준호"}


class FmStandbyTests(unittest.TestCase):
    def test_one_standby_when_two_or_more_off(self):
        staff = [StaffInput("A", "통제", True, False, None, True)]
        staff += [StaffInput(p, n, True, True, int(p), False) for p, n in NAMES.items()]
        result = run_schedule(ShiftRequest(date(2026, 10, 7), NightType.N1, Mode.FM, tuple(staff)),
                              HistorySelection(), SolveOptions(rules_version="2.20", seconds=30))
        self.assertTrue(result.valid, result.validation_errors)
        counts = {}
        for t in range(14):
            if t in (2, 10):
                continue
            rows = [r for r in result.record.assignments if r.slot.index == t]
            off = [r for r in rows if r.actual_work_time_value == 0
                   and r.displayed_assignment.label in ("휴게", "보안실 대기")]
            standby = [r for r in rows if r.displayed_assignment.label == "보안실 대기"]
            self.assertLessEqual(len(standby), 1, t)
            if len(off) >= 2:
                self.assertEqual(len(standby), 1, t)
            for r in standby:
                counts[r.employee_id] = counts.get(r.employee_id, 0) + 1
        values = [counts.get(r, 0) for r in ["A", *NAMES]]
        self.assertLessEqual(max(values) - min(values), 1, counts)


if __name__ == "__main__":
    unittest.main()
