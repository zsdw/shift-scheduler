"""8-9: 00시 이후 관리자 L3 연속 배치 강한 비권장."""
import unittest
from datetime import date

from night_shift.models import Mode, NightType
from night_shift.service import HistorySelection, ShiftRequest, SolveOptions, StaffInput, run_schedule

NAMES = {"1": "만년", "2": "원종", "3": "제욱", "4": "광희", "5": "성호", "6": "준호"}


class ManagerL3Tests(unittest.TestCase):
    def test_no_consecutive_l3_after_midnight(self):
        for night, absent in ((NightType.N1, set()), (NightType.N2, {"2"})):
            staff = [StaffInput("A", "통제", True, False, None, True)]
            staff += [StaffInput(p, n, p not in absent, True, int(p) if p not in absent else None, False)
                      for p, n in NAMES.items()]
            result = run_schedule(ShiftRequest(date(2026, 10, 7), night, Mode.FM, tuple(staff)),
                                  HistorySelection(), SolveOptions(rules_version="2.20", seconds=20))
            self.assertTrue(result.valid, result.validation_errors)
            labels = {r.slot.index: r.displayed_assignment.label for r in result.record.assignments
                      if r.employee_id == "A"}
            for t in range(6, 13):
                self.assertFalse(labels[t] == labels[t + 1] == "L3", (night, t, labels))


if __name__ == "__main__":
    unittest.main()
