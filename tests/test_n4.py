import unittest
from datetime import date

from night_shift.common import compile_common_policy
from night_shift.models import Attendance, Employee, HistoryInput, Mode, NightType, ShiftContext
from night_shift.profiles import make_record
from night_shift.solver import solve_first_trial
from night_shift.validator import validate_first_trial


def context():
    employees = tuple(Employee(str(i), f"일반 {i}") for i in range(1, 6)) + (Employee("A", "통제 A"),)
    attendance = tuple(Attendance(str(i), True, True, i, False) for i in range(1, 6)) + (Attendance("A", True, False, None, True),)
    return ShiftContext(date(2026, 10, 3), NightType.N4, Mode.FM, Mode.FM, employees, attendance)


class N4Tests(unittest.TestCase):
    def test_weekend_post_facts_and_requirements(self):
        c = context()
        policy = compile_common_policy(c)
        self.assertFalse(any(x.displayed_post.startswith("G2") or x.displayed_post == "G3" for x in policy.requirements))
        for t in (0, 13):
            row = make_record(c, "1", t, "I1", patrol_standing=True)
            self.assertEqual((row.actual_post_or_work_type.label, row.fatigue_value), ("I1", 1))
        manager_l3 = make_record(c, "A", 0, "L3", patrol_standing=True)
        self.assertEqual((manager_l3.actual_post_or_work_type.label, manager_l3.fatigue_value), ("L3", 2))

    def test_generated_schedule_validates(self):
        c = context()
        h = HistoryInput((), ())
        result = solve_first_trial(c, h, seconds=20, rules_v210=True)
        self.assertIsNotNone(result.record, result.attempts)
        self.assertEqual(validate_first_trial(result.record, h, rules_v210=True), [])


if __name__ == "__main__":
    unittest.main()
