"""§10-4: N3/N4 유도리 20시 차단봉 설치는 I1 + 보안실 대기."""
import unittest
from collections import Counter
from datetime import date

from night_shift.models import Mode, NightType
from night_shift.service import HistorySelection, ShiftRequest, SolveOptions, StaffInput, run_schedule

NAMES = {"1": "만년", "2": "원종", "3": "제욱", "4": "광희", "5": "성호", "6": "준호"}


class N34FlexibleTests(unittest.TestCase):
    def test_installers(self):
        for night, absent in ((NightType.N4, set()), (NightType.N3, set()), (NightType.N4, {"2"})):
            staff = [StaffInput("A", "통제", True, False, None, True)]
            staff += [StaffInput(p, n, p not in absent, True, int(p) if p not in absent else None, False)
                      for p, n in NAMES.items()]
            result = run_schedule(ShiftRequest(date(2026, 10, 3), night, Mode.FLEXIBLE, tuple(staff)),
                                  HistorySelection(), SolveOptions(rules_version="2.20", seconds=30))
            self.assertTrue(result.valid, (night, absent, result.validation_errors))
            installers = Counter(r.displayed_assignment.label for r in result.record.assignments
                                 if r.barrier_install_flag)
            self.assertEqual(installers, Counter(["I1", "보안실 대기"]), night)


if __name__ == "__main__":
    unittest.main()
