import unittest
from datetime import date

from night_shift.common import compile_common_policy
from night_shift.models import Attendance, Employee, HistoryInput, Mode, NightType, ShiftContext
from night_shift.profiles import make_record
from night_shift.solver import solve_first_trial
from night_shift.validator import validate_first_trial


def context():
    employees = tuple(Employee(str(i), f"일반 {i}") for i in range(1, 7)) + (Employee("A", "통제 A"),)
    attendance = tuple(Attendance(str(i), True, True, i, False) for i in range(1, 7)) + (Attendance("A", True, False, None, True),)
    return ShiftContext(date(2026, 9, 28), NightType.N2, Mode.FM, Mode.FM, employees, attendance)


class N2Tests(unittest.TestCase):
    def test_evening_gate_and_no_morning_gate(self):
        c = context()
        policy = compile_common_policy(c)
        gates = [(r.slot_index,r.displayed_post) for r in policy.requirements if r.displayed_post in ("G2","G3","G2(1)")]
        self.assertEqual(gates, [(0,"G2"),(0,"G3"),(1,"G2"),(2,"G2")])
        self.assertEqual((make_record(c,"1",0,"I1").actual_post_or_work_type.label,
                          make_record(c,"1",13,"I1").actual_post_or_work_type.label), ("L3","I1"))

    def test_generated_schedule_validates(self):
        c = context()
        h = HistoryInput((), ())
        result = solve_first_trial(c, h, seconds=25, rules_v210=True)
        self.assertIsNotNone(result.record, result.attempts)
        self.assertEqual(validate_first_trial(result.record, h, rules_v210=True), [])


if __name__ == "__main__":
    unittest.main()
